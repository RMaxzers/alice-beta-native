<#
.SYNOPSIS  Copia de seguridad consistente de Alice: SQLite (API de backup), Qdrant servidor (snapshots), data\ y manifiesto.
.DESCRIPTION
  Modo por defecto (consistente entre almacenes): detiene el proceso propio alice-api para pausar TODAS las mutaciones
  (ingestión, borrado, hechos, ledger), hace la copia y vuelve a arrancar Alice con Start-Alice.ps1.
  -Online: no detiene la API. Cada almacén queda consistente por sí mismo (SQLite backup API, snapshot de Qdrant), pero
  la correspondencia documentos/catálogo/vectores NO está garantizada si hay una ingestión en curso. El manifiesto lo registra.
  Salida: backups\alice-<fecha>\ (excluido de Git, ACL solo para el usuario actual). Retención: -Keep copias.
  .env NO se incluye (secretos); guárdalo aparte si lo necesitas.
.OUTPUTS   exit 0 = backup completo; 1 = error (la carpeta parcial se elimina); 2 = requisito no cumplido.
#>
param(
  [string]$Destination = (Join-Path (Resolve-Path "$PSScriptRoot\..\..").Path 'backups'),
  [int]$Keep = 3,   # each Qdrant snapshot is ~545 MB even for a few points (preallocated segments)
  [switch]$Online,
  [string]$QdrantUrl = 'http://127.0.0.1:6333'
)
. "$PSScriptRoot\_common.ps1"
$Destination = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination)
$py = Join-Path $Root '.venv\Scripts\python.exe'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$final = Join-Path $Destination "alice-$stamp"
$work = "$final.partial"
$stoppedApi = $false

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

try {
  if (-not (Test-Http "$QdrantUrl/healthz" 5)) { Write-Host "Qdrant no responde en $QdrantUrl" -ForegroundColor Red; exit 2 }
  New-Item -ItemType Directory -Force $work, (Join-Path $work 'sqlite'), (Join-Path $work 'qdrant') | Out-Null
  & icacls $work /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" "SYSTEM:(OI)(CI)F" | Out-Null

  if (-not $Online) {
    Step 'Pausando mutaciones: deteniendo alice-api (proceso propio)'
    if (Get-OwnPid 'alice-api') { & "$PSScriptRoot\Stop-Alice.ps1" -Only alice-api; $stoppedApi = $true }
    elseif (Test-Http 'http://127.0.0.1:8000/healthz' 3) { throw 'La API está en marcha pero no es un proceso propio: detenla a mano o usa -Online' }
  }

  Step 'SQLite (sqlite3 backup API vía el python del venv)'
  $code = @'
import json, pathlib, sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(pathlib.Path(src).as_uri() + '?mode=ro', uri=True, timeout=30)
d = sqlite3.connect(dst)
s.backup(d)
ok = d.execute('PRAGMA integrity_check').fetchone()[0]
tables = [r[0] for r in d.execute('SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE ?', ('table', 'sqlite_%'))]
counts = {t: d.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0] for t in tables}
d.close(); s.close()
print(json.dumps(dict(integrity=ok, counts=counts, sqlite_version=sqlite3.sqlite_version)))
'@
  $sqlite = [ordered]@{}
  foreach ($db in Get-ChildItem (Join-Path $Root 'storage\sqlite') -Filter *.db) {
    $out = & $py -c $code $db.FullName (Join-Path $work "sqlite\$($db.Name)")
    if ($LASTEXITCODE) { throw "backup SQLite falló: $($db.Name)" }
    $r = $out | ConvertFrom-Json
    if ($r.integrity -ne 'ok') { throw "integrity_check de $($db.Name): $($r.integrity)" }
    $sqlite[$db.Name] = $r
    Write-Host ("  {0,-10} integrity=ok tablas={1}" -f $db.Name, @($r.counts.PSObject.Properties).Count)
  }

  Step 'Qdrant servidor (snapshot por colección, descargado y borrado del servidor)'
  $qv = (Invoke-RestMethod "$QdrantUrl/" -TimeoutSec 10).version
  $qdrant = [ordered]@{}
  foreach ($c in (Invoke-RestMethod "$QdrantUrl/collections" -TimeoutSec 10).result.collections.name) {
    $snap = (Invoke-RestMethod "$QdrantUrl/collections/$c/snapshots?wait=true" -Method Post -TimeoutSec 300).result
    $file = Join-Path $work "qdrant\$c.snapshot"
    Invoke-WebRequest "$QdrantUrl/collections/$c/snapshots/$($snap.name)" -OutFile $file -TimeoutSec 600 -UseBasicParsing
    $null = Invoke-RestMethod "$QdrantUrl/collections/$c/snapshots/$($snap.name)" -Method Delete -TimeoutSec 60
    $info = (Invoke-RestMethod "$QdrantUrl/collections/$c" -TimeoutSec 10).result
    $qdrant[$c] = [ordered]@{ points = $info.points_count; vector_size = $info.config.params.vectors.size; snapshot = "qdrant/$c.snapshot" }
    Write-Host ("  {0,-14} points={1} snapshot={2:N1} MB" -f $c, $info.points_count, ((Get-Item $file).Length / 1MB))
  }

  Step 'Datos originales y derivados (data\raw, data\processed, data\verified)'
  foreach ($d in 'raw', 'processed', 'verified') {
    $src = Join-Path $Root "data\$d"
    if (Test-Path $src) { Copy-Item $src (Join-Path $work "data\$d") -Recurse -Force }
    else { New-Item -ItemType Directory -Force (Join-Path $work "data\$d") | Out-Null }
  }

  Step 'Manifiesto (versiones, recuentos, SHA256 de cada archivo)'
  $files = foreach ($f in Get-ChildItem $work -Recurse -File) {
    [ordered]@{ path = $f.FullName.Substring($work.Length + 1).Replace('\', '/'); bytes = $f.Length; sha256 = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower() }
  }
  $commit = try { (& git -C $Root rev-parse --short HEAD 2>$null) } catch { $null }
  $ver = (Select-String -Path (Join-Path $Root 'pyproject.toml') -Pattern '^version\s*=\s*"(.+)"').Matches[0].Groups[1].Value
  $manifest = [ordered]@{
    format = 'alice-backup/1'; created_utc = (Get-Date).ToUniversalTime().ToString('o'); host = $env:COMPUTERNAME
    alice_version = $ver; git_commit = $commit
    consistency = $(if ($Online) { 'online: por almacén (SQLite backup API + snapshot Qdrant); correspondencia entre almacenes no garantizada' } else { 'offline: alice-api detenida durante la copia; mutaciones pausadas' })
    vector_store = [ordered]@{ mode = 'server'; product = 'qdrant'; version = $qv; url = $QdrantUrl; collections = $qdrant }
    sqlite = $sqlite; env_included = $false; files = @($files)
  }
  $manifest | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $work 'manifest.json') -Encoding utf8
  Move-Item $work $final
  Write-Host "Backup completo: $final ($(@($files).Count) archivos)" -ForegroundColor Green

  Step "Retención: se conservan las $Keep copias más recientes"
  Get-ChildItem $Destination -Directory -Filter 'alice-*' | Where-Object { $_.Name -notlike '*.partial' } |
    Sort-Object Name -Descending | Select-Object -Skip $Keep | ForEach-Object { Remove-Item $_.FullName -Recurse -Force; Write-Host "  eliminado $($_.Name)" }
  $rc = 0
} catch {
  Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
  if (Test-Path $work) { Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue }
  $rc = 1
} finally {
  if ($stoppedApi) { Step 'Reanudando: Start-Alice.ps1'; & "$PSScriptRoot\Start-Alice.ps1" | Out-Null }
}
exit $rc
