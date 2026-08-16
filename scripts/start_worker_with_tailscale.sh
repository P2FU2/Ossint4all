#!/usr/bin/env bash
# Worker Railway + Tailscale userspace → alcança proxy DJEN no PC (100.x).
# Variáveis: TS_AUTHKEY (obrigatória), DJEN_HTTP_PROXY=http://100.x.y.z:8899
set -euo pipefail

if [[ -z "${TS_AUTHKEY:-}" ]]; then
  echo "TS_AUTHKEY ausente — gere em https://login.tailscale.com/admin/settings/keys"
  exit 1
fi

if ! command -v tailscaled >/dev/null 2>&1; then
  echo "Instalando Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
fi

tailscaled --tun=userspace-networking --socks5-server=localhost:1055 --outbound-http-proxy-listen=localhost:1055 &
sleep 2
tailscale up --authkey="${TS_AUTHKEY}" --hostname="${TS_HOSTNAME:-monitor-jus-worker}" --accept-dns=false

echo "Tailscale up. DJEN_HTTP_PROXY=${DJEN_HTTP_PROXY:-"(não definido)"}"
exec python -m monitor_jus.main worker
