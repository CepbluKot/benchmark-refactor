#!/usr/bin/env bash
set -euo pipefail

chain=BENCH_PREV_EGRESS
host_chain=BENCH_PREV_HOST
subnet=172.29.87.0/29

iptables -N DOCKER-USER 2>/dev/null || true
ensure_policy_chain() {
  local policy_chain=$1
  local hook=$2
  local actual_rules expected_rules

  if ! iptables -S "$policy_chain" >/dev/null 2>&1; then
    iptables -N "$policy_chain"
    iptables -A "$policy_chain" -s "$subnet" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    iptables -A "$policy_chain" -s "$subnet" -j DROP
    iptables -A "$policy_chain" -j RETURN
  else
    actual_rules=$(iptables -S "$policy_chain" | sed -n '2,$p')
    expected_rules=$(printf '%s\n' \
      "-A $policy_chain -s $subnet -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT" \
      "-A $policy_chain -s $subnet -j DROP" \
      "-A $policy_chain -j RETURN")
    [[ "$actual_rules" == "$expected_rules" ]] || {
      echo "Existing $policy_chain rules differ from the managed preview policy; refusing to alter them." >&2
      exit 1
    }
  fi

  iptables -C "$hook" -j "$policy_chain" 2>/dev/null || iptables -I "$hook" 1 -j "$policy_chain"
}

ensure_policy_chain "$chain" DOCKER-USER
ensure_policy_chain "$host_chain" INPUT
