#!/usr/bin/env bash
set -euo pipefail

release_dir=${1:-}
credentials_file=${HOMELAB_VPS_CREDENTIALS:-/home/oleg/Documents/homelab/new-vpn/secrets/credentials.local.md}
vps_host=${VPS_HOST:-10.19.87.1}
[[ -d "$release_dir" && -f "$release_dir/patch_hosting_config.py" ]] || {
  echo "Usage: $0 RELEASE_DIRECTORY" >&2
  exit 2
}
[[ -r "$credentials_file" ]] || { echo "VPS credentials file is unavailable." >&2; exit 1; }
command -v sshpass >/dev/null || { echo "sshpass is required for the documented VPS credential." >&2; exit 1; }
release_id=$(sed -n 's/^release_id=//p' "$release_dir/manifest.txt")
[[ "$release_id" =~ ^[a-f0-9]{16}$ ]] || { echo "Invalid release id." >&2; exit 1; }

read_vps_password() {
  awk '
    /^## VPS evita/ { in_section = 1; next }
    /^## / && in_section { exit }
    in_section && /^- Пароль:/ {
      sub(/^- Пароль:[[:space:]]*/, "")
      gsub(/`/, "")
      print
      exit
    }
  ' "$credentials_file"
}

vps_ssh() {
  sshpass -d 3 ssh -o PreferredAuthentications=password \
    -o PubkeyAuthentication=no -o StrictHostKeyChecking=yes "$@" \
    3< <(read_vps_password)
}

vps_scp() {
  sshpass -d 3 scp -o PreferredAuthentications=password \
    -o PubkeyAuthentication=no -o StrictHostKeyChecking=yes "$@" \
    3< <(read_vps_password)
}

remote_stage="/tmp/benchmark-studio-hosting-$release_id"
vps_ssh root@"$vps_host" "install -d -m 700 '$remote_stage'"
vps_scp "$release_dir/patch_hosting_config.py" \
  root@"$vps_host:$remote_stage/patch_hosting_config.py"

vps_ssh root@"$vps_host" "bash -s -- '$release_id' '$remote_stage/patch_hosting_config.py'" <<'REMOTE_SCRIPT'
set -euo pipefail
exec 9>/run/lock/benchmark-studio-hosting.lock
flock -n 9 || { echo 'Another benchmark hosting update is running.' >&2; exit 1; }
release_id=$1
patcher=$2
dns_root=/opt/awesomeio-dns
managed_caddy=$dns_root/caddy/Caddyfile
active_caddy=/etc/caddy/Caddyfile
portal_inventory=$dns_root/portal/inventory.json
config_dir=$dns_root/generated/powerdns
zone=lan.awesomeio.ru

test -f "$managed_caddy" && test -f "$active_caddy" && test -f "$portal_inventory"
cmp -s "$managed_caddy" "$active_caddy" || {
  echo 'Managed and active Caddyfile differ; refusing an unreviewed overwrite.' >&2
  exit 1
}
stamp=$(date -u +%Y%m%d-%H%M%S)
stamp="$stamp-$$"
managed_backup="$managed_caddy.bak-$stamp"
active_backup="$active_caddy.bak-$stamp"
portal_backup="$portal_inventory.bak-$stamp"
cp -a "$managed_caddy" "$managed_backup"
cp -a "$active_caddy" "$active_backup"
cp -a "$portal_inventory" "$portal_backup"
mkdir -p "$dns_root/backups"
zone_backup="$dns_root/backups/lan-awesomeio-ru-$stamp-before-benchmark.zone"
pdnsutil --config-dir="$config_dir" list-zone "$zone" >"$zone_backup"
chmod 600 "$zone_backup"
page_file=$(mktemp /tmp/benchmark-hosting-XXXXXX.html)

rollback() {
  status=$?
  rm -f "$page_file"
  if ((status != 0)); then
    cp -a "$managed_backup" "$managed_caddy"
    cp -a "$active_backup" "$active_caddy"
    cp -a "$portal_backup" "$portal_inventory"
    caddy reload --config "$active_caddy" --adapter caddyfile >/dev/null 2>&1 || true
    if [[ ${old_dns:-} == '192.168.20.68' ]]; then
      pdnsutil --config-dir="$config_dir" replace-rrset "$zone" benchmark A "${old_ttl:-300}" 192.168.20.68 >/dev/null || true
    elif [[ ${old_dns:-} == '10.19.87.1' ]]; then
      pdnsutil --config-dir="$config_dir" replace-rrset "$zone" benchmark A "${old_ttl:-300}" 10.19.87.1 >/dev/null || true
    elif [[ ${old_dns:-} == 'absent' ]]; then
      pdnsutil --config-dir="$config_dir" delete-rrset "$zone" benchmark A >/dev/null 2>&1 || true
    fi
  fi
  exit "$status"
}
trap rollback EXIT

python3 "$patcher" "$managed_caddy" "$active_caddy" "$portal_inventory"
caddy validate --config "$active_caddy" --adapter caddyfile
systemctl reload caddy.service
systemctl is-active --quiet caddy.service
curl -fsS --max-time 10 --resolve benchmark.lan.awesomeio.ru:443:10.19.87.1 \
  -o "$page_file" https://benchmark.lan.awesomeio.ru/
grep -Fq 'DDL Benchmark Engine' "$page_file"
curl -fsS --max-time 10 --resolve benchmark.lan.awesomeio.ru:443:10.19.87.1 \
  https://benchmark.lan.awesomeio.ru/api/v1/bootstrap >/dev/null
run_status=$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' \
  --resolve benchmark.lan.awesomeio.ru:443:10.19.87.1 \
  -X POST https://benchmark.lan.awesomeio.ru/api/v1/runs \
  -H 'Content-Type: application/json' -d '{}')
[[ "$run_status" == 503 ]]

rrset=$(pdnsutil --config-dir="$config_dir" list-zone "$zone" | awk '$1 == "benchmark.lan.awesomeio.ru" { print $2 " " $4 " " $5 }')
old_dns=absent
old_ttl=300
if [[ -n "$rrset" ]]; then
  read -r old_ttl record_type old_dns <<<"$rrset"
  [[ "$record_type" == 'A' && ( "$old_dns" == '192.168.20.68' || "$old_dns" == '10.19.87.1' ) ]] || {
    echo 'Existing benchmark DNS record differs from the reviewed target.' >&2
    exit 1
  }
fi
pdnsutil --config-dir="$config_dir" replace-rrset "$zone" benchmark A 300 10.19.87.1
pdnsutil --config-dir="$config_dir" check-zone "$zone"
resolved=$(pdnsutil --config-dir="$config_dir" list-zone "$zone" | awk '$1 == "benchmark.lan.awesomeio.ru" { print $5 }')
[[ "$resolved" == '10.19.87.1' ]]
rm -f "$page_file"
trap - EXIT
printf 'Private Caddy route and DNS are active; backups: %s %s %s %s\n' \
  "$managed_backup" "$active_backup" "$portal_backup" "$zone_backup"
REMOTE_SCRIPT

echo "Private HTTPS domain configured: https://benchmark.lan.awesomeio.ru/"
