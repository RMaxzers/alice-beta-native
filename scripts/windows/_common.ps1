# Shared helpers for Alice Windows scripts. Dot-source only.
$ErrorActionPreference = 'Stop'
$Script:Root   = (Resolve-Path "$PSScriptRoot\..\..").Path
$Script:Bin    = Join-Path $Root 'infra\bin'
$Script:RunDir = Join-Path $Root 'storage\run'
$Script:LogDir = Join-Path $Root 'logs'
$Script:Ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
$Script:Uv     = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) { $Script:Uv = Join-Path $env:LOCALAPPDATA 'hermes\bin\uv.exe' }

# Pinned versions + official SHA256 (release checksum files / GitHub asset digest).
$Script:Versions = @{
  qdrant     = @{ ver='1.19.1';  url='https://github.com/qdrant/qdrant/releases/download/v1.19.1/qdrant-x86_64-pc-windows-msvc.zip'; sha='9b6f69bd85f6abed4bc13f943099f55c6ffd55f5dd90388635320d8fbb569eb0' }
  prometheus = @{ ver='3.14.0';  url='https://github.com/prometheus/prometheus/releases/download/v3.14.0/prometheus-3.14.0.windows-amd64.zip'; sha='e57fbb99e4d0bc734d2f2b3aeb68c02fba38862259dc99a95c27ea46d9ccba0a' }
  grafana    = @{ ver='13.2.2';  url='https://dl.grafana.com/oss/release/grafana-13.2.2.windows-amd64.zip'; sha='7f2854e288c12395ad0170368bfc77c0c192a6d98ae6c3452917055cfd78b8cf' }
  winexp     = @{ ver='0.31.8';  url='https://github.com/prometheus-community/windows_exporter/releases/download/v0.31.8/windows_exporter-0.31.8-amd64.exe'; sha='03bb0fe80b8ad0b4e39606b96c4c5cc56b1f766760011ea2b00111157c6ef077' }
}

function Read-DotEnv([string]$Path = (Join-Path $Root '.env')) {
  $h = @{}
  if (Test-Path $Path) {
    foreach ($l in Get-Content $Path) {
      if ($l -match '^\s*([A-Za-z0-9_]+)\s*=(.*)$') { $h[$Matches[1]] = $Matches[2].Trim() }
    }
  }
  $h
}

function Test-Http([string]$Url, [int]$TimeoutSec = 3) {
  try { $r = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing; return $r.StatusCode -lt 400 } catch { return $false }
}

# --- Process manifest (storageun\<name>.json): pid + start time + executable + logs.
# A PID is only "ours" if all three still match; a reused PID never gets stopped by mistake.
function Save-Manifest([string]$Name, $Proc) {
  [ordered]@{
    name = $Name; pid = $Proc.Id; exe = $Proc.Path
    start_utc_ticks = $Proc.StartTime.ToUniversalTime().Ticks; start = $Proc.StartTime.ToString('o')
    stdout = (Join-Path $LogDir "$Name.out.log"); stderr = (Join-Path $LogDir "$Name.err.log")
  } | ConvertTo-Json | Set-Content (Join-Path $RunDir "$Name.json") -Encoding utf8
}

function Get-OwnPid([string]$Name) {
  $f = Join-Path $RunDir "$Name.json"; $legacy = Join-Path $RunDir "$Name.pid"
  if (Test-Path $legacy) {
    # Migrate a pre-manifest PID file only if it still points at a binary inside this project.
    $p = Get-Process -Id ([int](Get-Content $legacy)) -ErrorAction SilentlyContinue
    if (-not (Test-Path $f) -and $p -and $p.Path -and $p.Path.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase)) { Save-Manifest $Name $p }
    Remove-Item $legacy -Force
  }
  if (-not (Test-Path $f)) { return $null }
  $m = Get-Content $f -Raw | ConvertFrom-Json
  $p = Get-Process -Id $m.pid -ErrorAction SilentlyContinue
  if ($p -and $p.Path -eq $m.exe -and [math]::Abs($p.StartTime.ToUniversalTime().Ticks - [long]$m.start_utc_ticks) -lt 10000000) { return $p.Id }
  Remove-Item $f -Force; $null
}

function Start-Owned([string]$Name, [string]$Exe, [string[]]$ArgList, [hashtable]$Env = @{}, [string]$WorkDir = $Root) {
  if (Get-OwnPid $Name) { return }
  foreach ($k in $Env.Keys) { Set-Item "env:$k" $Env[$k] }
  $p = Start-Process -FilePath $Exe -ArgumentList $ArgList -WorkingDirectory $WorkDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir "$Name.out.log") -RedirectStandardError (Join-Path $LogDir "$Name.err.log")
  foreach ($k in $Env.Keys) { Remove-Item "env:$k" -ErrorAction SilentlyContinue }
  Save-Manifest $Name (Get-Process -Id $p.Id)
}

# Kill an owned process and its children (the venv python.exe is a launcher whose child runs the API).
function Stop-OwnedTree([int]$Id) {
  & taskkill.exe /PID $Id /T /F 2>&1 | Out-Null
  Wait-Process -Id $Id -Timeout 10 -ErrorAction SilentlyContinue
}

# Export owned PIDs (and their direct children) for windows_exporter's textfile collector so Grafana can
# join windows_process_* on process_id. Ollama is included as owned="false" when it was reused, not started.
function Write-ProcessMetrics {
  $dir = Join-Path $RunDir 'textfile'; New-Item -ItemType Directory -Force $dir | Out-Null
  $all = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, Name
  $rows = @()
  function Add-Tree([string]$component, [int]$id, [string]$owned) {
    $Script:rows += "alice_native_process{component=`"$component`",owned=`"$owned`",process_id=`"$id`"} 1"
    foreach ($c in $all | Where-Object { $_.ParentProcessId -eq $id -and $_.Name -ne 'conhost.exe' }) {
      $Script:rows += "alice_native_process{component=`"$component`",owned=`"$owned`",process_id=`"$($c.ProcessId)`"} 1"
    }
  }
  $Script:rows = @()
  foreach ($f in Get-ChildItem $RunDir -Filter *.json) { $id = Get-OwnPid $f.BaseName; if ($id) { Add-Tree $f.BaseName $id 'true' } }
  if (-not (Get-OwnPid 'ollama')) {
    $o = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($o) { Add-Tree 'ollama' $o.OwningProcess 'false' }
  }
  $body = @('# HELP alice_native_process Processes of the Alice stack (from storage/run manifests).', '# TYPE alice_native_process gauge') + $Script:rows
  $tmp = Join-Path $dir 'alice_processes.tmp'
  Set-Content $tmp $body -Encoding ascii
  Move-Item $tmp (Join-Path $dir 'alice_processes.prom') -Force
}

function Wait-Http([string]$Url, [int]$Seconds = 30) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) { if (Test-Http $Url) { return $true }; Start-Sleep -Milliseconds 500 }
  $false
}
