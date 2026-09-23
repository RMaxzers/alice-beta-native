<#
.SYNOPSIS  Valida un backup de Alice y lo restaura SOLO en un destino explícito; después comprueba la correspondencia
           documentos / catálogo / vectores.
.DESCRIPTION
  1. Valida manifest.json y el SHA256 de cada archivo (cualquier diferencia aborta antes de escribir nada).
  2. Restaura en -Destination con la misma estructura que la raíz del proyecto:
       storage\sqlite\*.db, storage\qdrant\data (vía snapshots), data\raw|processed|verified
  3. Qdrant: arranca un qdrant.exe TEMPORAL (binario fijado de infra\bin) en 127.0.0.1:-QdrantPort con almacenamiento en
     el destino, sube cada snapshot, compara el número de puntos con el manifiesto y lo detiene (salvo -KeepQdrant).
  4. Verifica: recuentos SQLite = manifiesto; puntos Qdrant = filas de chunks = suma de documents.chunks (documentos ready);
     cada documents.stored_path existe en data\ restaurado.
  Salvaguardas: el destino debe estar vacío o no existir. Restaurar sobre la instalación activa exige -Force Y que
  la API (8000) y Qdrant (6333) estén detenidos (Stop-Alice.ps1). Nunca toca el Qdrant activo.
.OUTPUTS   exit 0 = restaurado y verificado; 1 = verificación fallida; 2 = backup inválido o salvaguarda.
#>
param(
  [Parameter(Mandatory)][string]$Backup,
  [Parameter(Mandatory)][string]$Destination,
  [switch]$Force,
  [int]$QdrantPort = 6343,
  [switch]$KeepQdrant
)
. "$PSScriptRoot\_common.ps1"
$py = Join-Path $Root '.venv\Scripts\python.exe'
function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Fail([int]$code, $m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit $code }

$Backup = (Resolve-Path $Backup).Path
$Destination = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination)  # relative to the PS location, not the process cwd

Step "Validando $Backup"
$mf = Join-Path $Backup 'manifest.json'
if (-not (Test-Path $mf)) { Fail 2 'manifest.json no existe' }
$m = Get-Content $mf -Raw -Encoding utf8 | ConvertFrom-Json
if ($m.format -ne 'alice-backup/1') { Fail 2 "formato de manifiesto desconocido: $($m.format)" }
$badSum = 0
foreach ($f in $m.files) {
  $p = Join-Path $Backup $f.path
  if (-not (Test-Path $p) -or (Get-FileHash $p -Algorithm SHA256).Hash.ToLower() -ne $f.sha256) { Write-Host "  checksum FAIL $($f.path)" -ForegroundColor Red; $badSum++ }
}
if ($badSum) { Fail 2 "$badSum archivo(s) no coinciden con el manifiesto" }
Write-Host "  $(@($m.files).Count) archivos OK; creado $($m.created_utc); vector store $($m.vector_store.mode) qdrant $($m.vector_store.version); $($m.consistency)"

Step "Salvaguardas del destino $Destination"
$isLive = $Destination.TrimEnd('\') -ieq $Root.TrimEnd('\')
if ($isLive) {
  if (-not $Force) { Fail 2 'el destino es la instalación activa: usa -Force (y detén Alice antes)' }
  if ((Test-Http 'http://127.0.0.1:8000/healthz' 3) -or (Test-Http 'http://127.0.0.1:6333/healthz' 3)) { Fail 2 'API o Qdrant activos: ejecuta Stop-Alice.ps1 antes de restaurar sobre la instalación activa' }
  foreach ($d in 'storage\sqlite', 'storage\qdrant\data', 'data\raw', 'data\processed', 'data\verified') {
    $p = Join-Path $Root $d
    if (Test-Path $p) { $aside = "$p.pre-restore-$(Get-Date -Format yyyyMMdd-HHmmss)"; Move-Item $p $aside; Write-Host "  apartado $d -> $(Split-Path $aside -Leaf)" }
  }
} elseif ((Test-Path $Destination) -and (Get-ChildItem $Destination -Force | Select-Object -First 1)) {
  Fail 2 'el destino existe y no está vacío (no se sobrescribe nada)'
}
if (Get-NetTCPConnection -LocalPort $QdrantPort -State Listen -ErrorAction SilentlyContinue) { Fail 2 "el puerto $QdrantPort ya está en uso; elige otro con -QdrantPort" }

Step 'Restaurando SQLite y datos'
$sq = Join-Path $Destination 'storage\sqlite'
New-Item -ItemType Directory -Force $sq | Out-Null
Get-ChildItem (Join-Path $Backup 'sqlite') -Filter *.db | ForEach-Object { Copy-Item $_.FullName (Join-Path $sq $_.Name) }
foreach ($d in 'raw', 'processed', 'verified') {
  $src = Join-Path $Backup "data\$d"; $dst = Join-Path $Destination "data\$d"
  New-Item -ItemType Directory -Force $dst | Out-Null
  if (Test-Path $src) { Get-ChildItem $src -Force | Copy-Item -Destination $dst -Recurse -Force }
}

Step "Restaurando Qdrant con un proceso temporal en 127.0.0.1:$QdrantPort"
$qexe = Join-Path $Bin "qdrant-$($Versions.qdrant.ver)\qdrant.exe"
$qroot = Join-Path $Destination 'storage\qdrant'
New-Item -ItemType Directory -Force (Join-Path $qroot 'data'), (Join-Path $qroot 'snapshots') | Out-Null
$envs = @{ QDRANT__SERVICE__HOST = '127.0.0.1'; QDRANT__SERVICE__HTTP_PORT = "$QdrantPort"; QDRANT__SERVICE__GRPC_PORT = "$($QdrantPort + 1)"
           QDRANT__STORAGE__STORAGE_PATH = (Join-Path $qroot 'data'); QDRANT__STORAGE__SNAPSHOTS_PATH = (Join-Path $qroot 'snapshots'); QDRANT__TELEMETRY_DISABLED = 'true' }
foreach ($k in $envs.Keys) { Set-Item "env:$k" $envs[$k] }
$qp = Start-Process $qexe -WorkingDirectory $qroot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $qroot 'restore.out.log') -RedirectStandardError (Join-Path $qroot 'restore.err.log')
foreach ($k in $envs.Keys) { Remove-Item "env:$k" }
$qurl = "http://127.0.0.1:$QdrantPort"
$fail = 0
try {
  if (-not (Wait-Http "$qurl/healthz" 30)) { throw 'el Qdrant temporal no arrancó' }
  foreach ($c in $m.vector_store.collections.PSObject.Properties) {
    $snap = Get-Item (Join-Path $Backup $c.Value.snapshot)
    $null = Invoke-RestMethod "$qurl/collections/$($c.Name)/snapshots/upload?priority=snapshot&wait=true" -Method Post -Form @{ snapshot = $snap } -TimeoutSec 600
    $pts = (Invoke-RestMethod "$qurl/collections/$($c.Name)" -TimeoutSec 10).result.points_count
    $ok = $pts -eq $c.Value.points
    Write-Host ("  {0,-14} puntos restaurados={1} manifiesto={2} {3}" -f $c.Name, $pts, $c.Value.points, $(if ($ok) { 'OK' } else { 'FAIL' }))
    if (-not $ok) { $fail++ }
    if ($c.Name -eq 'alice_chunks') { $Script:qdrantPoints = $pts }
  }
} catch { Write-Host "ERROR Qdrant: $($_.Exception.Message)" -ForegroundColor Red; $fail++ }
finally {
  if (-not $KeepQdrant) { & taskkill.exe /PID $qp.Id /T /F 2>&1 | Out-Null; Wait-Process -Id $qp.Id -Timeout 10 -ErrorAction SilentlyContinue }
  else { Write-Host "  Qdrant temporal sigue en $qurl (pid $($qp.Id)); detenlo con: taskkill /PID $($qp.Id) /T /F" }
}

Step 'Verificando correspondencia documentos / catálogo / vectores'
$code = @'
import json, os, pathlib, sqlite3, sys
root = pathlib.Path(sys.argv[1])
c = sqlite3.connect((root / 'storage' / 'sqlite' / 'alice.db').as_uri() + '?mode=ro', uri=True)
docs = c.execute('SELECT document_id, stored_path, status, chunks FROM documents').fetchall()
missing = [d[0] for d in docs if not (root / 'data' / d[1]).exists()]
out = dict(documents=len(docs), ready=sum(1 for d in docs if d[2] == 'ready'),
           chunk_rows=c.execute('SELECT COUNT(*) FROM chunks').fetchone()[0],
           catalog_chunks=sum(d[3] or 0 for d in docs if d[2] == 'ready'), missing_raw=missing)
counts = {}
for db in (root / 'storage' / 'sqlite').glob('*.db'):
    k = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
    counts[db.name] = {t: k.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0] for (t,) in k.execute('SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE ?', ('table', 'sqlite_%'))}
out['counts'] = counts
print(json.dumps(out))
'@
$v = & $py -c $code $Destination | ConvertFrom-Json
foreach ($db in $m.sqlite.PSObject.Properties) {
  foreach ($t in $db.Value.counts.PSObject.Properties) {
    $got = $v.counts.($db.Name).($t.Name)
    if ($got -ne $t.Value) { Write-Host "  FAIL $($db.Name).$($t.Name): restaurado=$got manifiesto=$($t.Value)" -ForegroundColor Red; $fail++ }
  }
}
Write-Host ("  documentos={0} (ready={1}); filas chunks={2}; suma documents.chunks={3}; puntos Qdrant={4}; raw ausentes={5}" -f
  $v.documents, $v.ready, $v.chunk_rows, $v.catalog_chunks, $Script:qdrantPoints, @($v.missing_raw).Count)
if ($v.chunk_rows -ne $v.catalog_chunks -or $v.chunk_rows -ne $Script:qdrantPoints) { Write-Host '  FAIL: catálogo, fragmentos y vectores no coinciden' -ForegroundColor Red; $fail++ }
if (@($v.missing_raw).Count) { Write-Host "  FAIL: originales ausentes: $($v.missing_raw -join ', ')" -ForegroundColor Red; $fail++ }

if ($fail) { Write-Host "Restauración con $fail fallo(s) de verificación en $Destination" -ForegroundColor Red; exit 1 }
Write-Host "Restauración verificada en $Destination" -ForegroundColor Green
if ($isLive) { Write-Host 'Siguiente paso: Start-Alice.ps1 (Qdrant activo leerá storage\qdrant\data restaurado).' }
