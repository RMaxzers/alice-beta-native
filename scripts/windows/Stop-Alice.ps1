<#
.SYNOPSIS  Stop only processes Alice started (PID files). Never deletes data; never touches an Ollama it did not start.
#>
. "$PSScriptRoot\_common.ps1"
foreach ($n in 'grafana', 'prometheus', 'alice-api', 'windows_exporter', 'qdrant', 'ollama') {
  $id = Get-OwnPid $n
  if ($id) {
    Stop-Process -Id $id -ErrorAction SilentlyContinue
    Wait-Process -Id $id -Timeout 10 -ErrorAction SilentlyContinue
    if (Get-Process -Id $id -ErrorAction SilentlyContinue) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
    Remove-Item (Join-Path $RunDir "$n.pid") -Force -ErrorAction SilentlyContinue
    Write-Host ("stopped {0,-17} pid {1}" -f $n, $id)
  } else { Write-Host ("not running (owned) {0}" -f $n) }
}
