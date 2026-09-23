<#
.SYNOPSIS  Prepara y verifica los datos sintéticos de la demo (data\samples) y, opcionalmente, los carga en Alice.
.DESCRIPTION
  Sin parámetros: solo verifica los checksums de data\samples\SHA256SUMS (no toca la instancia).
  -Load : inicia sesión en la API local (credenciales leídas de .env, nunca impresas), sube PDF/MD/CSV/LOG
          (duplicados detectados por checksum: idempotente), registra el hecho verificado si no existe y espera
          a que los documentos queden 'ready'.
  -Smoke: además lanza una consulta local corta («Explícame DHCP en pocas palabras») y muestra ruta y modelo.
.OUTPUTS   exit 0 = todo OK; 1 = checksum incorrecto o carga fallida; 2 = API no disponible.
#>
param([switch]$Load, [switch]$Smoke, [string]$Api = 'http://127.0.0.1:8000', [int]$TimeoutSec = 180)
. "$PSScriptRoot\_common.ps1"
$samples = Join-Path $Root 'data\samples'
$bad = 0

Write-Host '== Verificando data\samples (Dataset sintético de demostración)' -ForegroundColor Cyan
foreach ($l in Get-Content (Join-Path $samples 'SHA256SUMS')) {
  $sha, $name = $l -split '\s+\*?', 2
  $f = Join-Path $samples $name
  $ok = (Test-Path $f) -and ((Get-FileHash $f -Algorithm SHA256).Hash.ToLower() -eq $sha)
  Write-Host ("  {0,-4} {1}" -f $(if ($ok) { 'OK' } else { 'FAIL' }), $name) -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
  if (-not $ok) { $bad++ }
}
if ($bad) { Write-Host 'Checksums incorrectos: regenerar o restaurar data\samples desde Git.' -ForegroundColor Red; exit 1 }
if (-not ($Load -or $Smoke)) { exit 0 }

if (-not (Test-Http "$Api/healthz" 5)) { Write-Host "API no disponible en $Api (ejecuta Start-Alice.ps1)" -ForegroundColor Red; exit 2 }
$cfg = Read-DotEnv
$ws = $null
$login = @{ username = $cfg['ALICE_USERNAME']; password = $cfg['ALICE_PASSWORD'] } | ConvertTo-Json
$csrf = (Invoke-RestMethod "$Api/api/login" -Method Post -Body $login -ContentType 'application/json' -SessionVariable ws -TimeoutSec 15).csrf
$h = @{ 'x-csrf-token' = $csrf }

if ($Load) {
  Write-Host '== Cargando documentos de demo' -ForegroundColor Cyan
  $privacy = @{ '.pdf' = 'INTERNAL'; '.md' = 'INTERNAL'; '.csv' = 'INTERNAL'; '.log' = 'PRIVATE' }
  $ids = @()
  foreach ($f in Get-ChildItem $samples -File | Where-Object { $privacy.ContainsKey($_.Extension) -and $_.Name -ne 'README.md' }) {
    $r = Invoke-RestMethod "$Api/api/documents" -Method Post -WebSession $ws -Headers $h -Form @{ file = $f; privacy = $privacy[$f.Extension] } -TimeoutSec 60
    $ids += $r.document.document_id
    Write-Host ("  {0,-38} {1} {2}" -f $f.Name, $r.document.document_id, $(if ($r.duplicate) { '(ya existía)' } else { '(nuevo)' }))
  }
  $fact = Get-Content (Join-Path $samples 'hecho-verificado-demo.json') -Raw -Encoding utf8
  $key = ($fact | ConvertFrom-Json).subject_key
  $have = Invoke-RestMethod "$Api/api/facts?subject=$([uri]::EscapeDataString($key))" -WebSession $ws -TimeoutSec 15
  if (@($have.facts).Count) { Write-Host "  hecho $key (ya existía)" }
  else { $null = Invoke-RestMethod "$Api/api/facts" -Method Post -WebSession $ws -Headers $h -Body ([Text.Encoding]::UTF8.GetBytes($fact)) -ContentType 'application/json; charset=utf-8' -TimeoutSec 15; Write-Host "  hecho $key (nuevo)" }

  Write-Host '== Esperando ingestión' -ForegroundColor Cyan
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  do {
    $all = Invoke-RestMethod "$Api/api/documents" -WebSession $ws -TimeoutSec 15   # PS7 returns the JSON array as one object
    $docs = @($all | Where-Object { $_.document_id -in $ids })
    $pending = @($docs | Where-Object { $_.status -in 'pending', 'processing' })
    if (-not $pending) { break }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt $deadline)
  foreach ($d in $docs) {
    Write-Host ("  {0,-38} {1,-10} fragmentos={2} {3}" -f $d.original_name, $d.status, $d.chunks, $d.status_detail)
    if ($d.status -ne 'ready') { $bad++ }
  }
}

if ($Smoke) {
  Write-Host '== Consulta local de humo' -ForegroundColor Cyan
  $body = @{ message = 'Explícame DHCP en pocas palabras'; privacy = 'PUBLIC' } | ConvertTo-Json
  $raw = Invoke-WebRequest "$Api/api/chat" -Method Post -WebSession $ws -Headers $h -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json; charset=utf-8' -TimeoutSec $TimeoutSec
  $events = ([Text.Encoding]::UTF8.GetString($raw.RawContentStream.ToArray()) -split "`n" | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
  $route = $events | Where-Object type -eq 'route' | Select-Object -First 1
  $done = $events | Where-Object type -in 'done', 'final', 'end' | Select-Object -Last 1
  Write-Host "  tipos de evento: $(($events.type | Select-Object -Unique) -join ', ')"
  if ($route) { Write-Host "  ruta: $($route | ConvertTo-Json -Compress -Depth 3)" }
  if ($done) { Write-Host "  fin: $($done | ConvertTo-Json -Compress -Depth 3)" }
  if ($events.type -contains 'error') { $bad++ }
}
if ($bad) { exit 1 }
