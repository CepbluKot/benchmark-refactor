#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
docker_host=${DOCKER_HOST:-ssh://oleg@192.168.20.68}
output_dir=

usage() {
  printf '%s\n' "Usage: $0 [--docker-host HOST] [--output-dir PATH]"
}

while (($#)); do
  case "$1" in
    --docker-host)
      [[ $# -ge 2 ]] || { echo "--docker-host requires a value" >&2; exit 2; }
      docker_host=$2
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || { echo "--output-dir requires a path" >&2; exit 2; }
      output_dir=$2
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v docker >/dev/null || { echo "Docker CLI is required." >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required for the locked UI build." >&2; exit 1; }
command -v sha256sum >/dev/null || { echo "sha256sum is required." >&2; exit 1; }

ui_dir="$repo_root/apps/config_editor_ui"
dns_root=${HOMELAB_DNS_ROOT:-/home/oleg/Documents/homelab/dns-awesomeio}
[[ -r "$dns_root/records.tsv" && -r "$dns_root/caddy/Caddyfile" && -r "$dns_root/portal/inventory.json" ]] || {
  echo "Canonical homelab DNS/Caddy source files are unavailable." >&2
  exit 1
}
(
  cd "$ui_dir"
  npm run check:ui-kit
  npm run check:strategy-template
  npm run check:strategy-empty-search-space
  npm run check:source-type-autocomplete
  npm run check:alternative-focus
  npm run check:search-procedure-availability
  npm run typecheck
  npm run build
)
(
  cd "$dns_root"
  python3 -m unittest discover -s tests -v
)

source_digest=$(
  {
    find "$repo_root/apps/config_editor_ui/src" \
      "$repo_root/apps/config_editor_ui/public" \
      "$repo_root/apps/config_editor_ui/vendor" \
      "$repo_root/apps/config_editor_ui/dist" \
      "$repo_root/apps/realtime_control_api/src" \
      "$dns_root/caddy" \
      "$dns_root/portal" \
      "$script_dir" \
      -type f ! -path '*/tests/*' ! -path '*/__pycache__/*' ! -name '*.pyc' -print0
    printf '%s\0' \
      "$ui_dir/package.json" \
      "$ui_dir/package-lock.json" \
      "$ui_dir/index.html" \
      "$repo_root/deploy/benchmark_studio/requirements.lock" \
      "$dns_root/records.tsv"
  } | sort -zu | xargs -0 sha256sum | sha256sum | awk '{print $1}'
)

locked_images=()
while read -r source_image expected_id local_image; do
  [[ -n "${source_image:-}" ]] || continue
  [[ "$source_image" != \#* ]] || continue
  if actual_id=$(docker --host "$docker_host" image inspect "$local_image" --format '{{.Id}}' 2>/dev/null); then
    if [[ "$actual_id" != "$expected_id" ]]; then
      printf 'Pinned build base mismatch for %s: expected %s, found %s\n' "$local_image" "$expected_id" "$actual_id" >&2
      exit 1
    fi
  else
    actual_id=$(docker --host "$docker_host" image inspect "$source_image" --format '{{.Id}}')
    if [[ "$actual_id" != "$expected_id" ]]; then
      printf 'Base image mismatch for %s: expected %s, found %s\n' "$source_image" "$expected_id" "$actual_id" >&2
      exit 1
    fi
    docker --host "$docker_host" image tag "$source_image" "$local_image"
  fi
  locked_images+=("$local_image")
done <"$script_dir/base-images.lock"

docker --host "$docker_host" build --pull=false --network=none \
  --file "$script_dir/control.Dockerfile" \
  --tag benchmark-studio-control:local "$repo_root"
docker --host "$docker_host" build --pull=false --network=none \
  --file "$script_dir/ui.Dockerfile" \
  --tag benchmark-studio-ui:local "$repo_root"
docker --host "$docker_host" build --pull=false --network=none \
  --file "$script_dir/gateway.Dockerfile" \
  --tag benchmark-studio-gateway:local "$repo_root"

runtime_images=(
  benchmark-studio-postgres:local
  benchmark-studio-clickhouse:local
  benchmark-studio-control:local
  benchmark-studio-ui:local
  benchmark-studio-gateway:local
)
for image in "${runtime_images[@]}"; do
  docker --host "$docker_host" image inspect "$image" >/dev/null
done

image_digest=$(
  for image in "${locked_images[@]}" "${runtime_images[@]}"; do
    docker --host "$docker_host" image inspect "$image" --format '{{.RepoTags}} {{.Id}}'
  done | sort | sha256sum | awk '{print $1}'
)
release_id=$(printf '%s\n%s\n' "$source_digest" "$image_digest" | sha256sum | awk '{print substr($1, 1, 16)}')
if [[ -z "$output_dir" ]]; then
  output_dir="${TMPDIR:-/tmp}/benchmark-studio-release-$release_id"
fi
if [[ -e "$output_dir" ]]; then
  [[ -d "$output_dir" && -z "$(find "$output_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]] || {
    printf 'Output directory must be new or empty: %s\n' "$output_dir" >&2
    exit 1
  }
else
  mkdir -p "$output_dir"
fi
output_dir=$(cd -- "$output_dir" && pwd)

docker --host "$docker_host" save "${locked_images[@]}" "${runtime_images[@]}" | gzip -n -1 >"$output_dir/images.tar.gz"
test -s "$output_dir/images.tar.gz"
tar -tzf "$output_dir/images.tar.gz" >/dev/null
mkdir -p "$output_dir/clickhouse-init" "$output_dir/clickhouse-config"
dns_root=${HOMELAB_DNS_ROOT:-/home/oleg/Documents/homelab/dns-awesomeio}
mkdir -p "$output_dir/hosting-reference/caddy" "$output_dir/hosting-reference/portal"
cp "$script_dir/compose.yaml" "$script_dir/runtime-config.js" \
  "$script_dir/gateway.conf" "$script_dir/ui.conf" \
  "$script_dir/egress-guard.sh" "$script_dir/benchmark-studio-preview-egress.service" \
  "$script_dir/install-egress-guard.sh" \
  "$script_dir/patch_hosting_config.py" "$output_dir/"
cp "$script_dir/clickhouse-init/01-sandbox.sql" "$output_dir/clickhouse-init/"
cp "$script_dir/clickhouse-config/benchmark-preview-limits.xml" "$output_dir/clickhouse-config/"
cp "$dns_root/records.tsv" "$output_dir/hosting-reference/records.tsv"
cp "$dns_root/caddy/Caddyfile" "$output_dir/hosting-reference/caddy/Caddyfile"
cp "$dns_root/portal/inventory.json" "$output_dir/hosting-reference/portal/inventory.json"
{
  printf 'release_id=%s\n' "$release_id"
  printf 'source_tree_sha256=%s\n' "$source_digest"
  printf 'image_set_sha256=%s\n' "$image_digest"
  printf 'target_platform=linux/amd64\n'
  printf 'image_tag_policy=local-only\n'
  printf 'benchmark_execution=disabled-at-gateway\n'
  while read -r source_image expected_id local_image; do
    [[ -n "${source_image:-}" && "$source_image" != \#* ]] || continue
    printf 'base_image.%s=%s\n' "$local_image" "$expected_id"
  done <"$script_dir/base-images.lock"
  for image in "${runtime_images[@]}"; do
    image_id=$(docker --host "$docker_host" image inspect "$image" --format '{{.Id}}')
    printf 'runtime_image.%s=%s\n' "$image" "$image_id"
  done
} >"$output_dir/manifest.txt"
(cd "$output_dir" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >SHA256SUMS)

printf 'Release: %s\nArtifact: %s\n' "$release_id" "$output_dir"
sha256sum "$output_dir/images.tar.gz"
