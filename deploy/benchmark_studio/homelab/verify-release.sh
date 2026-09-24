#!/usr/bin/env bash
set -euo pipefail

release_id=${1:-}
vm_host=${2:-${VM_HOST:-oleg@192.168.20.68}}
[[ "$release_id" =~ ^[a-f0-9]{16}$ ]] || {
  echo "Usage: $0 RELEASE_ID [VM_HOST]" >&2
  exit 2
}

for attempt in {1..60}; do
  if ssh "$vm_host" "bash -s -- '$release_id'" <<'REMOTE_CHECK'
set -euo pipefail
release_id=$1
compose=(docker compose --project-name benchmark-studio-preview --env-file /home/oleg/benchmark-studio-preview/.env -f "/home/oleg/benchmark-studio-preview/releases/$release_id/compose.yaml")
all_healthy=true
for service in postgres clickhouse control-api gateway ui; do
  container=$("${compose[@]}" ps -q "$service")
  if [[ -z "$container" ]] || [[ $(docker inspect "$container" --format '{{.State.Health.Status}}') != healthy ]]; then
    all_healthy=false
  fi
done
[[ "$all_healthy" == true ]]
REMOTE_CHECK
  then break; fi
  if ((attempt == 60)); then
    echo "Timed out waiting for preview containers to become healthy." >&2
    ssh "$vm_host" "docker compose --project-name benchmark-studio-preview --env-file /home/oleg/benchmark-studio-preview/.env -f /home/oleg/benchmark-studio-preview/releases/$release_id/compose.yaml ps" >&2
    exit 1
  fi
  sleep 5
done

ssh "$vm_host" "bash -s -- '$release_id'" <<'REMOTE_RUNTIME_CHECK'
set -euo pipefail
release_id=$1
compose=(docker compose --project-name benchmark-studio-preview --env-file /home/oleg/benchmark-studio-preview/.env -f "/home/oleg/benchmark-studio-preview/releases/$release_id/compose.yaml")
clickhouse_container=$("${compose[@]}" ps -q clickhouse)
docker exec "$clickhouse_container" clickhouse-client --query "SELECT throwIf(count() != 0, 'unexpected seeded source table') FROM system.tables WHERE database = 'default' AND name = 'benchmark_events'" >/dev/null
[[ $(docker exec "$clickhouse_container" clickhouse-client --query "SELECT count() FROM system.users WHERE name = 'benchmark_writer'") == 1 ]]
[[ $(docker exec "$clickhouse_container" clickhouse-client --query "SELECT count() FROM system.databases WHERE name = 'benchmark_sandbox'") == 1 ]]
for image in benchmark-studio-postgres:local benchmark-studio-clickhouse:local benchmark-studio-control:local benchmark-studio-ui:local benchmark-studio-gateway:local; do
  docker image inspect "$image" >/dev/null
done
network_internal=$(docker network inspect benchmark-studio-preview --format '{{.Internal}}')
[[ "$network_internal" == true ]]
edge_internal=$(docker network inspect benchmark-studio-preview-edge --format '{{.Internal}}')
[[ "$edge_internal" == false ]]
edge_masquerade=$(docker network inspect benchmark-studio-preview-edge --format '{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}')
[[ "$edge_masquerade" == false ]]
systemctl is-enabled --quiet benchmark-studio-preview-egress.service
ui_container=$("${compose[@]}" ps -q ui)
gateway_container=$("${compose[@]}" ps -q gateway)
docker port "$ui_container" 8080/tcp | grep -Fqx '192.168.20.68:18901'
docker port "$gateway_container" 8080/tcp | grep -Fqx '192.168.20.68:18900'
docker run --rm --privileged --network host --pid host --user 0 --volume /:/host:ro \
  --entrypoint python benchmark-studio-control:local \
  -c 'import os; os.chroot("/host"); os.execv("/usr/sbin/iptables", ["iptables", "-C", "DOCKER-USER", "-j", "BENCH_PREV_EGRESS"])'
docker run --rm --privileged --network host --pid host --user 0 --volume /:/host:ro \
  --entrypoint python benchmark-studio-control:local \
  -c 'import os; os.chroot("/host"); os.execv("/usr/sbin/iptables", ["iptables", "-C", "INPUT", "-j", "BENCH_PREV_HOST"])'
REMOTE_RUNTIME_CHECK

response_file=$(mktemp)
trap 'rm -f "$response_file"' EXIT
curl --fail --silent --show-error --max-time 10 -o "$response_file" http://192.168.20.68:18901/
grep -Fq 'DDL Benchmark Engine' "$response_file"
curl --fail --silent --show-error --max-time 10 http://192.168.20.68:18900/health/ready >/dev/null
run_status=$(curl --silent --show-error --max-time 10 -o "$response_file" -w '%{http_code}' \
  -X POST http://192.168.20.68:18900/api/v1/runs \
  -H 'Content-Type: application/json' -d '{}')
[[ "$run_status" == 503 ]]
grep -Fq 'not available in this preview deployment' "$response_file"

curl --fail --silent --show-error --max-time 10 \
  --resolve benchmark.lan.awesomeio.ru:443:10.19.87.1 \
  -o "$response_file" https://benchmark.lan.awesomeio.ru/
grep -Fq 'DDL Benchmark Engine' "$response_file"
curl --fail --silent --show-error --max-time 10 \
  --resolve benchmark.lan.awesomeio.ru:443:10.19.87.1 \
  https://benchmark.lan.awesomeio.ru/api/v1/bootstrap >/dev/null
run_status=$(curl --silent --show-error --max-time 10 \
  --resolve benchmark.lan.awesomeio.ru:443:10.19.87.1 \
  -o "$response_file" -w '%{http_code}' \
  -X POST https://benchmark.lan.awesomeio.ru/api/v1/runs \
  -H 'Content-Type: application/json' -d '{}')
[[ "$run_status" == 503 ]]
grep -Fq 'not available in this preview deployment' "$response_file"

python3 - "$release_id" <<'PY'
import asyncio
import sys
import websockets

async def main() -> None:
    async with websockets.connect(
        "wss://benchmark.lan.awesomeio.ru/api/v1/events",
        host="10.19.87.1",
        server_hostname="benchmark.lan.awesomeio.ru",
        open_timeout=8,
    ):
        return

asyncio.run(main())
print(f"PASS: private UI/API/WebSocket, isolated preview, run gate; release {sys.argv[1]}")
PY
