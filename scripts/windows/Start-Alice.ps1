<#
.SYNOPSIS  Start Alice components in order (only ones not already running), then print verified status.
#>
. "$PSScriptRoot\_common.ps1"
$cfg = Read-DotEnv
$st  = Join-Path $Root 'storage'

# 1. Ollama (reuse a running instance; never started twice)
if (-not (Test-Http 'http://127.0.0.1:11434/api/version')) {
  Start-Owned 'ollama' $Ollama @('serve') @{ OLLAMA_HOST = '127.0.0.1:11434'; OLLAMA_MAX_LOADED_MODELS = '2'; OLLAMA_NUM_PARALLEL = '1'; OLLAMA_KEEP_ALIVE = '10m' }
}

# 2. Qdrant (loopback, telemetry off)
$q = $Versions.qdrant
Start-Owned 'qdrant' (Join-Path $Bin "qdrant-$($q.ver)\qdrant.exe") @() @{
  QDRANT__SERVICE__HOST = '127.0.0.1'; QDRANT__SERVICE__HTTP_PORT = '6333'; QDRANT__SERVICE__GRPC_PORT = '6334'
  QDRANT__STORAGE__STORAGE_PATH = (Join-Path $st 'qdrant\data'); QDRANT__STORAGE__SNAPSHOTS_PATH = (Join-Path $st 'qdrant\snapshots')
  QDRANT__TELEMETRY_DISABLED = 'true'
} (Join-Path $st 'qdrant')

# 3. windows_exporter (host metrics; user process, loopback)
$w = $Versions.winexp
Start-Owned 'windows_exporter' (Join-Path $Bin "winexp-$($w.ver)\windows_exporter-$($w.ver)-amd64.exe") @(
  '--web.listen-address=127.0.0.1:9182', '--collectors.enabled=cpu,memory,logical_disk,net,os,system,physical_disk')

# 4. Alice API (+ metrics on 9101)
$py = Join-Path $Root '.venv\Scripts\python.exe'
Start-Owned 'alice-api' $py @('-m', 'uvicorn', 'apps.api.main:app', '--host', '127.0.0.1', '--port', '8000', '--no-server-header', '--log-level', 'warning')

# 5. Prometheus
$p = $Versions.prometheus; $pdir = Join-Path $Bin "prometheus-$($p.ver)\prometheus-$($p.ver).windows-amd64"
Start-Owned 'prometheus' (Join-Path $pdir 'prometheus.exe') @(
  "--config.file=`"$(Join-Path $Root 'infra\prometheus\prometheus.yml')`"", "--storage.tsdb.path=`"$(Join-Path $st 'prometheus')`"",
  '--storage.tsdb.retention.time=7d', '--storage.tsdb.retention.size=2GB', '--web.listen-address=127.0.0.1:9090')

# 6. Grafana (anonymous off, admin from .env, provisioning from repo)
$g = $Versions.grafana; $gdir = Join-Path $Bin "grafana-$($g.ver)\grafana-$($g.ver)"
Start-Owned 'grafana' (Join-Path $gdir 'bin\grafana.exe') @('server', '--homepath', "`"$gdir`"") @{
  GF_SERVER_HTTP_ADDR = '127.0.0.1'; GF_SERVER_HTTP_PORT = '3000'
  GF_PATHS_DATA = (Join-Path $st 'grafana'); GF_PATHS_LOGS = (Join-Path $LogDir 'grafana'); GF_PATHS_PLUGINS = (Join-Path $st 'grafana\plugins')
  GF_PATHS_PROVISIONING = (Join-Path $Root 'infra\grafana\provisioning'); ALICE_GRAFANA_DASHBOARDS = (Join-Path $Root 'infra\grafana\dashboards')
  GF_SECURITY_ADMIN_USER = 'admin'; GF_SECURITY_ADMIN_PASSWORD = $cfg['GRAFANA_ADMIN_PASSWORD']
  GF_AUTH_ANONYMOUS_ENABLED = 'false'; GF_USERS_ALLOW_SIGN_UP = 'false'; GF_SECURITY_COOKIE_SECURE = 'false'
  GF_ANALYTICS_REPORTING_ENABLED = 'false'; GF_ANALYTICS_CHECK_FOR_UPDATES = 'false'; GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES = 'false'
  GF_NEWS_NEWS_FEED_ENABLED = 'false'; GF_SERVER_ROOT_URL = 'http://127.0.0.1:3000/'
}

# Wait for health, then ensure the tailnet Viewer account (idempotent; admin creds never leave this script).
$null = Wait-Http 'http://127.0.0.1:6333/healthz' 30
$null = Wait-Http 'http://127.0.0.1:8000/healthz' 60
$null = Wait-Http 'http://127.0.0.1:9090/-/ready' 30
if (Wait-Http 'http://127.0.0.1:3000/api/health' 60) {
  $pair = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("admin:$($cfg['GRAFANA_ADMIN_PASSWORD'])"))
  $h = @{ Authorization = "Basic $pair" }
  try { $null = Invoke-RestMethod 'http://127.0.0.1:3000/api/users/lookup?loginOrEmail=viewer' -Headers $h }
  catch {
    $body = @{ name = 'Alice Viewer'; login = 'viewer'; email = 'viewer@alice.local'; password = $cfg['GRAFANA_VIEWER_PASSWORD'] } | ConvertTo-Json
    try { $null = Invoke-RestMethod 'http://127.0.0.1:3000/api/admin/users' -Method Post -Headers $h -Body $body -ContentType 'application/json' } catch { Write-Warning "Could not create Grafana viewer: $($_.Exception.Message)" }
  }
}

& "$PSScriptRoot\Status-Alice.ps1"
