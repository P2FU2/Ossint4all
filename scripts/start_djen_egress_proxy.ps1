# Proxy DJEN no PC (IP Brasil) — Railway alcança via Tailscale.
# Pré-requisito: Tailscale instalado e conectado neste PC.
#
# 1) Descubra o IP Tailscale:  tailscale ip -4
# 2) Rode este script (deixe a janela aberta)
# 3) No Railway (worker), variáveis:
#      DJEN_HTTP_PROXY=http://SEU_IP_TAILSCALE:8899
#    e o serviço worker precisa estar na mesma tailnet (Tailscale sidecar / auth key).
# 4) Teste no worker:  python -m monitor_jus.sources.djen.probe

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (Test-Path .\.venv\Scripts\python.exe) {
  $py = ".\.venv\Scripts\python.exe"
} else {
  $py = "python"
}

Write-Host "IP Tailscale deste PC (use no Railway):"
try {
  & tailscale ip -4
} catch {
  Write-Host "(tailscale CLI não encontrado — veja o IP no app Tailscale)"
}

Write-Host ""
Write-Host "Iniciando proxy na porta 8899 ..."
& $py -m monitor_jus.sources.djen.egress_proxy --host 0.0.0.0 --port 8899
