#!/usr/bin/env bash
set -euo pipefail

previous_release_id=${1:-}
vm_host=${2:-${VM_HOST:-oleg@192.168.20.68}}
[[ "$previous_release_id" =~ ^[a-f0-9]{16}$ ]] || {
  echo "Usage: $0 PREVIOUS_RELEASE_ID [VM_HOST]" >&2
  exit 2
}
remote_root=/home/oleg/benchmark-studio-preview
remote_release="$remote_root/releases/$previous_release_id"
ssh "$vm_host" "set -euo pipefail
test -f '$remote_release/compose.yaml'
(cd '$remote_release' && sha256sum -c SHA256SUMS)
grep -Fqx 'benchmark_execution=disabled-at-gateway' '$remote_release/manifest.txt'
docker compose --project-name benchmark-studio-preview --env-file '$remote_root/.env' -f '$remote_release/compose.yaml' config --quiet
docker compose --project-name benchmark-studio-preview --env-file '$remote_root/.env' -f '$remote_release/compose.yaml' up -d --no-build --pull never
ln -s '$remote_release' '$remote_root/current.new'
mv -Tf '$remote_root/current.new' '$remote_root/current'
"
echo "Rolled back application containers to release $previous_release_id; database volumes were preserved."
