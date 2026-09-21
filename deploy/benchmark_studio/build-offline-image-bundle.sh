#!/usr/bin/env bash
# Build every image used by the local benchmark studio stack and save them as
# one compressed archive that can be imported with `docker load -i`.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
compose_file="$script_dir/compose.yaml"
env_file="$script_dir/.env.example"
output_file="$script_dir/benchmark-studio-images.tar.gz"
build_images=true

usage() {
  cat <<'EOF'
Usage: ./build-offline-image-bundle.sh [options]

Builds the images declared in compose.yaml and packs them into one archive.
The result can be imported in an isolated contour with:

  docker load -i benchmark-studio-images.tar.gz

Options:
  --output PATH  Write the archive to PATH.
  --no-build     Do not build application images before packaging.
  --help         Show this message.
EOF
}

while (($#)); do
  case "$1" in
    --output)
      [[ $# -ge 2 ]] || { echo "--output requires a path" >&2; exit 2; }
      output_file=$2
      shift 2
      ;;
    --no-build)
      build_images=false
      shift
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

command -v docker >/dev/null || { echo "Docker is not installed." >&2; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose v2 is required." >&2; exit 1; }

compose=(docker compose --env-file "$env_file" -f "$compose_file")

if "$build_images"; then
  "${compose[@]}" build
fi

mapfile -t images < <("${compose[@]}" config --images | sort -u)
(( ${#images[@]} > 0 )) || { echo "No images were found in $compose_file." >&2; exit 1; }

missing_images=()
for image in "${images[@]}"; do
  docker image inspect "$image" >/dev/null 2>&1 || missing_images+=("$image")
done
if (( ${#missing_images[@]} > 0 )); then
  printf 'Images are missing locally:\n' >&2
  printf '  %s\n' "${missing_images[@]}" >&2
  echo "Build or import them before creating the bundle." >&2
  exit 1
fi

output_dir=$(dirname -- "$output_file")
mkdir -p "$output_dir"
output_file=$(cd -- "$output_dir" && pwd)/$(basename -- "$output_file")
temporary_gzip=$(mktemp "$output_dir/.$(basename -- "$output_file").XXXXXX.tmp")
trap 'rm -f "$temporary_gzip"' EXIT

docker save "${images[@]}" | gzip -n > "$temporary_gzip"
test -s "$temporary_gzip"
tar -tzf "$temporary_gzip" >/dev/null
mv -f "$temporary_gzip" "$output_file"

printf 'Created %s\n' "$output_file"
printf 'Images:\n'
printf '  %s\n' "${images[@]}"
printf 'SHA-256: '
sha256sum "$output_file" | awk '{print $1}'
