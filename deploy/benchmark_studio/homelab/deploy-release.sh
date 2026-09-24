#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
release_dir=${1:-}
vm_host=${VM_HOST:-oleg@192.168.20.68}
remote_root=/home/oleg/benchmark-studio-preview

if [[ -z "$release_dir" || ! -d "$release_dir" ]]; then
  echo "Usage: $0 RELEASE_DIRECTORY" >&2
  exit 2
fi
release_dir=$(cd -- "$release_dir" && pwd)
(cd "$release_dir" && sha256sum -c SHA256SUMS)
release_id=$(sed -n 's/^release_id=//p' "$release_dir/manifest.txt")
[[ "$release_id" =~ ^[a-f0-9]{16}$ ]] || { echo "Invalid release id." >&2; exit 1; }
grep -Fqx 'image_tag_policy=local-only' "$release_dir/manifest.txt"
grep -Fqx 'benchmark_execution=disabled-at-gateway' "$release_dir/manifest.txt"

remote_release="$remote_root/releases/$release_id"
local_manifest=$(<"$release_dir/manifest.txt")
remote_manifest=$(ssh "$vm_host" "if test -f '$remote_release/manifest.txt'; then cat '$remote_release/manifest.txt'; fi")
if [[ -n "$remote_manifest" ]]; then
  [[ "$remote_manifest" == "$local_manifest" ]] || { echo "Remote release id exists with a different manifest." >&2; exit 1; }
else
  ssh "$vm_host" "set -euo pipefail; mkdir -p '$remote_root/releases'; test ! -e '$remote_release'; mkdir '$remote_release'"
  scp "$release_dir/compose.yaml" "$release_dir/runtime-config.js" \
    "$release_dir/gateway.conf" "$release_dir/ui.conf" \
    "$release_dir/patch_hosting_config.py" "$release_dir/install-egress-guard.sh" \
    "$release_dir/egress-guard.sh" "$release_dir/benchmark-studio-preview-egress.service" \
    "$release_dir/manifest.txt" \
    "$release_dir/SHA256SUMS" "$release_dir/images.tar.gz" \
    "$vm_host:$remote_release/"
  scp -r "$release_dir/clickhouse-init" "$vm_host:$remote_release/"
  scp -r "$release_dir/clickhouse-config" "$vm_host:$remote_release/"
  scp -r "$release_dir/hosting-reference" "$vm_host:$remote_release/"
fi
ssh "$vm_host" "set -euo pipefail; cd '$remote_release'; sha256sum -c SHA256SUMS"

ssh "$vm_host" "set -euo pipefail
exec 9>/run/lock/benchmark-studio-preview-deploy.lock
flock -n 9 || { echo 'Another preview deployment is running.' >&2; exit 1; }
root='$remote_root'
if [ ! -e \"\$root/.env\" ]; then
  umask 077
  secret=\$(openssl rand -hex 32)
  temp=\$(mktemp \"\$root/.env.XXXXXX\")
  printf 'CONTROL_DB_PASSWORD=%s\\n' \"\$secret\" >\"\$temp\"
  unset secret
  chmod 600 \"\$temp\"
  mv \"\$temp\" \"\$root/.env\"
fi
chmod 600 \"\$root/.env\"
docker load --input '$remote_release/images.tar.gz'
docker run --rm --privileged --network host --pid host --user 0 --volume /:/host:rw \\
  --entrypoint python benchmark-studio-control:local \\
  -c 'import os,sys; os.chroot(sys.argv[1]); os.execv(sys.argv[2], sys.argv[2:])' \\
  /host /bin/bash '$remote_release/install-egress-guard.sh' '$remote_release'
docker compose --project-name benchmark-studio-preview --env-file \"\$root/.env\" -f '$remote_release/compose.yaml' config --quiet
docker compose --project-name benchmark-studio-preview --env-file \"\$root/.env\" -f '$remote_release/compose.yaml' up -d --no-build --pull never --wait --wait-timeout 180 postgres clickhouse ui
docker compose --project-name benchmark-studio-preview --env-file \"\$root/.env\" -f '$remote_release/compose.yaml' exec -T clickhouse clickhouse-client --multiquery < '$remote_release/clickhouse-init/01-sandbox.sql'
docker compose --project-name benchmark-studio-preview --env-file \"\$root/.env\" -f '$remote_release/compose.yaml' up -d --no-build --pull never --wait --wait-timeout 180
ln -s '$remote_release' \"\$root/current.new\"
mv -Tf \"\$root/current.new\" \"\$root/current\"
"

"$script_dir/configure-hosting.sh" "$release_dir"
"$script_dir/verify-release.sh" "$release_id" "$vm_host"
