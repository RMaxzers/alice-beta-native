<#
.SYNOPSIS  Detiene solo los procesos que Alice arrancó (manifiestos storage\run\*.json: PID + hora de inicio + ejecutable).
           Nunca borra datos; nunca toca un Ollama que no arrancó. Mata el árbol del proceso (el python.exe del venv
           es un lanzador cuyo hijo ejecuta la API).
.PARAMETER Only  Limita la parada a estos componentes, p. ej. -Only alice-api
#>
param([string[]]$Only)
. "$PSScriptRoot\_common.ps1"
foreach ($n in 'grafana', 'prometheus', 'alice-api', 'pocket-tts', 'hindsight', 'windows_exporter', 'qdrant', 'ollama') {
  if ($Only -and $n -notin $Only) { continue }
  $id = Get-OwnPid $n
  if ($id) {
    Stop-OwnedTree $id
    Remove-Item (Join-Path $RunDir "$n.json") -Force -ErrorAction SilentlyContinue
    Write-Host ("detenido {0,-17} pid {1}" -f $n, $id)
  } else { Write-Host ("no estaba en marcha (propio) {0}" -f $n) }
}
