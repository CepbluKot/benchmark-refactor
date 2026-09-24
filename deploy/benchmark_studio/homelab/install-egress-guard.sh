#!/usr/bin/env bash
set -euo pipefail

release_dir=${1:-}
[[ -d "$release_dir" && -f "$release_dir/egress-guard.sh" && -f "$release_dir/benchmark-studio-preview-egress.service" ]] || {
  echo "Usage: $0 RELEASE_DIRECTORY" >&2
  exit 2
}

install -o root -g root -m 0755 "$release_dir/egress-guard.sh" \
  /usr/local/sbin/benchmark-studio-preview-egress-guard
install -o root -g root -m 0644 "$release_dir/benchmark-studio-preview-egress.service" \
  /etc/systemd/system/benchmark-studio-preview-egress.service
systemctl daemon-reload
systemctl enable --now benchmark-studio-preview-egress.service
systemctl is-active --quiet benchmark-studio-preview-egress.service
/usr/local/sbin/benchmark-studio-preview-egress-guard
iptables -C DOCKER-USER -j BENCH_PREV_EGRESS
iptables -C INPUT -j BENCH_PREV_HOST
