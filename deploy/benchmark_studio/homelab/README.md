# Private homelab preview

This release is an isolated preview of the currently integrated Benchmark
Studio, not the production optimizer described in `docs/TARGET_ARCHITECTURE_REFACTOR.md`.
It persists Studio configuration in a fresh PostgreSQL volume, creates an empty
ClickHouse sandbox, and has no source connection configured. The unauthenticated
benchmark-run endpoint returns HTTP 503 at the gateway. Do not register real
source credentials or use this preview to make database-design decisions.

The private address is `https://benchmark.lan.awesomeio.ru/`. DNS points to the
WireGuard VPS Caddy listener; Caddy permits only the VPN and homelab LAN ranges.
The application VM ports bind only to `192.168.20.68`. PostgreSQL, ClickHouse,
and the API use an internal Docker network. The two static Nginx frontends use a
dedicated bridge for host-port publishing; Docker masquerading is disabled and a
dedicated `DOCKER-USER` rule blocks new outbound traffic from that edge subnet.
The guard is installed as a systemd unit ordered before Docker on boot. The
deployment verifier checks its chain hook, network settings, host bindings, and
private end-to-end paths.

## Deterministic release path

From the repository root, with the locked UI dependencies already installed and
the homelab Docker host reachable over SSH:

```sh
bash deploy/benchmark_studio/homelab/build-release.sh \
  --docker-host ssh://oleg@192.168.20.68
```

The script runs focused UI checks and the homelab DNS/Caddy unit suite, verifies
the exact cached base-image IDs in `base-images.lock`, builds with pull and build
network access disabled, tags every built/deployed image `:local`, and writes a
release directory containing its image archive, manifest, and checksums. It
never packages `.env` or credentials. The release ID binds the source tree and
exact runtime image IDs.

Deploy the printed release directory:

```sh
bash deploy/benchmark_studio/homelab/deploy-release.sh \
  /tmp/benchmark-studio-release-<release-id>
```

The deployment loads the checksummed local-tagged images, creates a random
database password on the VM only if one does not already exist, starts a new
Compose project with new named volumes, idempotently applies the empty sandbox
SQL after ClickHouse is healthy (including recovery from an interrupted first
initialization), then merges only the Benchmark Caddy and
portal entries into the live files. It backs those files up before editing,
validates Caddy before reloading, and updates only the existing Benchmark A
record from `192.168.20.68` to `10.19.87.1`. It does not stop or remove
`benchmark-studio-test` containers/volumes and never runs `down -v`.

Verification checks container health, volume/network isolation, absence of the
old seeded sample table in the new ClickHouse, direct VM and private HTTPS UI/API
health, WebSocket handshake, and the run-endpoint guard. The configured source
host is deliberately unresolvable, so a real source connection or benchmark
result is not part of this preview.

To restore an earlier application release while keeping the same data volumes:

```sh
bash deploy/benchmark_studio/homelab/rollback-release.sh <previous-release-id>
```

The process is a fixed shell/Docker/Caddy operation; no LLM call is used to
build, deploy, configure the private hostname, verify, or roll back a release.
