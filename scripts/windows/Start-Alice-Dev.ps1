<#
.SYNOPSIS
  Run the Alice API/UI from this checkout with isolated development data and ports.
.DESCRIPTION
  Starts only the API in the foreground. It never starts, stops, or connects to the
  production Qdrant, Hindsight, TTS, Prometheus, or Alice ports. Ctrl+C stops this API.
#>
[CmdletBinding()]
param(
  [string]$PythonPath = $env:ALICE_DEV_PYTHON,
  [switch]$ValidateOnly,
  [switch]$InitializeOnly
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$WorkRoot = [IO.Path]::GetFullPath((Join-Path $Root 'work'))
$DevRoot = [IO.Path]::GetFullPath((Join-Path $WorkRoot 'dev-data'))
$Paths = [ordered]@{
  Data = Join-Path $DevRoot 'data'
  Storage = Join-Path $DevRoot 'storage'
  Logs = Join-Path $DevRoot 'logs'
  Files = Join-Path $DevRoot 'alice-files'
  Credentials = Join-Path $DevRoot '.dev-credentials'
}

$DevProfile = [ordered]@{
  ApiHost = '127.0.0.1'; ApiPort = 8200; MetricsPort = 9211
  QdrantUrl = 'http://127.0.0.1:6353'; QdrantCollection = 'alice_chunks_integration'
  HindsightUrl = 'http://127.0.0.1:8898'; TtsUrl = 'http://127.0.0.1:8020'
  PrometheusUrl = 'http://127.0.0.1:9095'; GrafanaUrl = 'http://127.0.0.1:3003'
}

function Test-PathWithin([string]$Path, [string]$Parent) {
  $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
  $fullParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
  return $fullPath.Equals($fullParent, [StringComparison]::OrdinalIgnoreCase) -or
    $fullPath.StartsWith($fullParent + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoReparseAncestors([string]$Path) {
  $cursor = [IO.Path]::GetFullPath($Path)
  while ($cursor) {
    if (Test-Path -LiteralPath $cursor) {
      $item = Get-Item -LiteralPath $cursor -Force
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Perfil de desarrollo rechazado: '$cursor' es un reparse point/junction."
      }
    }
    $parent = [IO.Directory]::GetParent($cursor)
    if (-not $parent) { break }
    $cursor = $parent.FullName
  }
}

function Assert-IsolatedLayout {
  if (-not (Test-PathWithin $DevRoot $WorkRoot) -or $DevRoot.Equals($WorkRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Perfil de desarrollo rechazado: los datos deben vivir dentro de work\dev-data.'
  }
  foreach ($name in @('data', 'storage', 'logs', 'backups')) {
    $protectedPath = Join-Path $Root $name
    foreach ($path in @($DevRoot) + @($Paths.Values)) {
      if (Test-PathWithin $path $protectedPath) {
        throw "Perfil de desarrollo rechazado: '$path' se solapa con '$protectedPath'."
      }
    }
  }
  foreach ($path in @($Root, $WorkRoot, $DevRoot) + @($Paths.Values)) {
    Assert-NoReparseAncestors $path
  }

  $devPorts = @($DevProfile.ApiPort, $DevProfile.MetricsPort, 6353, 8898, 8020, 8643, 9095, 3003)
  $productionPorts = @(8000, 9101, 6333, 6334, 8888, 8010, 8642, 9090, 3000, 9182)
  if (($devPorts | Select-Object -Unique).Count -ne $devPorts.Count) {
    throw 'Perfil de desarrollo rechazado: hay puertos de desarrollo duplicados.'
  }
  $overlap = @($devPorts | Where-Object { $_ -in $productionPorts })
  if ($overlap.Count -gt 0) {
    throw "Perfil de desarrollo rechazado: puertos reservados por producción: $($overlap -join ', ')."
  }
}

function Get-RandomHex([int]$ByteCount) {
  $bytes = [byte[]]::new($ByteCount)
  $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  return [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
}

function Protect-CredentialsFile([string]$Path) {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
  $icacls = (Get-Command icacls.exe -ErrorAction Stop).Source
  & $icacls $Path '/reset' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "No pude restablecer el ACL de '$Path' (icacls exit $LASTEXITCODE)." }
  & $icacls $Path '/grant:r' ('*{0}:(F)' -f $identity.Value) | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "No pude autorizar al usuario actual en '$Path' (icacls exit $LASTEXITCODE)." }
  & $icacls $Path '/grant' '*S-1-5-18:(F)' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "No pude autorizar a SYSTEM en '$Path' (icacls exit $LASTEXITCODE)." }
  & $icacls $Path '/inheritance:r' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "No pude quitar la herencia del ACL de '$Path' (icacls exit $LASTEXITCODE)." }
}

function Get-DevCredentials {
  $path = $Paths.Credentials
  $content = $null
  if (-not (Test-Path -LiteralPath $path)) {
    $content = "ALICE_USERNAME=integracion`nALICE_PASSWORD=$(Get-RandomHex 32)`nALICE_SESSION_SECRET=$(Get-RandomHex 48)`n"
    $stream = $null
    try {
      $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    } catch [IO.IOException] {
      if (-not (Test-Path -LiteralPath $path)) { throw }
    } finally {
      if ($stream) { $stream.Dispose() }
    }
  }
  $item = Get-Item -LiteralPath $path -Force
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'Perfil de desarrollo rechazado: el archivo de credenciales es un reparse point.'
  }
  Protect-CredentialsFile $path
  if ($content) {
    [IO.File]::WriteAllText($path, $content, [Text.UTF8Encoding]::new($false))
  }
  $values = @{}
  foreach ($line in Get-Content -LiteralPath $path) {
    if ($line -match '^(ALICE_USERNAME|ALICE_PASSWORD|ALICE_SESSION_SECRET)=(.*)$') {
      $values[$Matches[1]] = $Matches[2]
    }
  }
  foreach ($key in @('ALICE_USERNAME', 'ALICE_PASSWORD', 'ALICE_SESSION_SECRET')) {
    if (-not $values[$key]) { throw "Credenciales de desarrollo inválidas; falta $key en '$path'." }
  }
  if ($values.ALICE_USERNAME -ne 'integracion' -or $values.ALICE_PASSWORD.Length -lt 32 -or $values.ALICE_SESSION_SECRET.Length -lt 64) {
    throw "Credenciales de desarrollo inválidas en '$path'; no se reemplazaron automáticamente."
  }
  return $values
}

function Set-DevelopmentEnvironment([hashtable]$Credentials) {
  $settings = [ordered]@{
    ALICE_ENV = 'integration'; ALICE_HOST = $DevProfile.ApiHost; ALICE_PORT = "$($DevProfile.ApiPort)"
    ALICE_METRICS_PORT = "$($DevProfile.MetricsPort)"; ALICE_PUBLIC_ORIGIN = ''
    ALICE_USERNAME = $Credentials.ALICE_USERNAME; ALICE_PASSWORD = $Credentials.ALICE_PASSWORD
    ALICE_SESSION_SECRET = $Credentials.ALICE_SESSION_SECRET; ALICE_FILE_ROOT = $Paths.Files
    ALICE_EXECUTOR_NAME = 'integracion-dev'; ALICE_LOCAL_ONLY = 'true'; ALICE_CLOUD_ENABLED = 'false'
    OPENROUTER_API_KEY = ''; DEEPSEEK_API_KEY = ''; ANTHROPIC_API_KEY = ''; OPENAI_API_KEY = ''
    GEMINI_API_KEY = ''; TAVILY_API_KEY = ''; NOTEBOOKLM_ENABLED = 'false'; EMAIL_ENABLED = 'false'
    OLLAMA_BASE_URL = 'http://127.0.0.1:11434'; HERMES_ENABLED = 'false'; HERMES_API_URL = 'http://127.0.0.1:8643'
    DOCKER_ENABLED = 'false'; DOCKER_ALLOWED_CONTAINERS = ''; GRAFANA_EXTERNAL_ENABLED = 'false'
    GRAFANA_URL = ''; GRAFANA_SERVICE_ACCOUNT_TOKEN = ''; LOKI_ENABLED = 'false'
    MEMORY_ENABLED = 'false'; HINDSIGHT_URL = $DevProfile.HindsightUrl
    VOICE_ENABLED = 'false'; TTS_URL = $DevProfile.TtsUrl
    QDRANT_URL = $DevProfile.QdrantUrl; QDRANT_COLLECTION = $DevProfile.QdrantCollection
    PROMETHEUS_URL = $DevProfile.PrometheusUrl; ALICE_GRAFANA_LOCAL_URL = $DevProfile.GrafanaUrl
    DATA_DIR = $Paths.Data; STORAGE_DIR = $Paths.Storage; LOGS_DIR = $Paths.Logs
  }
  $previous = @{}
  foreach ($key in $settings.Keys) {
    $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
    [Environment]::SetEnvironmentVariable($key, [string]$settings[$key], 'Process')
  }
  return $previous
}

function Restore-Environment([hashtable]$Previous, [string[]]$Keys) {
  foreach ($key in $Keys) {
    [Environment]::SetEnvironmentVariable($key, $Previous[$key], 'Process')
  }
}

Assert-IsolatedLayout

if (-not $PythonPath) { $PythonPath = Join-Path $Root '.venv\Scripts\python.exe' }
if (-not $ValidateOnly -and -not $InitializeOnly) {
  if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "No encuentro Python en '$PythonPath'. Pasa -PythonPath o define ALICE_DEV_PYTHON con un entorno que tenga las dependencias del proyecto."
  }
  $PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
}

if ($ValidateOnly) {
  Write-Host 'Perfil integration válido; no se crearon archivos ni se iniciaron procesos.'
  Write-Host "API: http://$($DevProfile.ApiHost):$($DevProfile.ApiPort) | métricas: $($DevProfile.MetricsPort)"
  Write-Host "Datos: $DevRoot | Qdrant: $($DevProfile.QdrantUrl) | Hindsight: $($DevProfile.HindsightUrl) | TTS: $($DevProfile.TtsUrl)"
  Write-Host 'Solo loopback; nube, memoria y voz desactivadas.'
  return
}

if (-not $InitializeOnly) {
  foreach ($port in @($DevProfile.ApiPort, $DevProfile.MetricsPort)) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
      throw "No se inicia el perfil: el puerto $port ya está ocupado (PID $($listener.OwningProcess)). No se detuvo ningún proceso."
    }
  }
}

foreach ($path in @($DevRoot, $Paths.Data, $Paths.Storage, $Paths.Logs, $Paths.Files)) {
  New-Item -ItemType Directory -Path $path -Force | Out-Null
  Assert-NoReparseAncestors $path
}
$credentials = Get-DevCredentials
if ($InitializeOnly) {
  Write-Host 'Perfil integration inicializado; no se iniciaron procesos.'
  Write-Host "Usuario: integracion | archivo de credenciales protegido: $($Paths.Credentials)"
  Write-Host "Datos aislados bajo: $DevRoot"
  return
}
$previous = Set-DevelopmentEnvironment $credentials
$keys = @($previous.Keys)
$exitCode = 0
try {
  Push-Location $Root
  try {
    $uiIndex = Join-Path $Root 'apps\web\dist\index.html'
    if (-not (Test-Path -LiteralPath $uiIndex)) {
      Write-Warning 'No existe apps\web\dist\index.html; la API arrancará, pero la UI devolverá 503. Ejecuta npm ci y npm run build en apps\web.'
    }
    Write-Host "Alice integration en http://$($DevProfile.ApiHost):$($DevProfile.ApiPort) (Ctrl+C para detener)."
    Write-Host "Usuario: integracion | archivo de credenciales protegido: $($Paths.Credentials)"
    Write-Host "Storage, datos, logs y carpeta de archivos están aislados bajo: $DevRoot"
    & $PythonPath -m uvicorn apps.api.main:app --host $DevProfile.ApiHost --port $DevProfile.ApiPort --no-server-header --log-level info
    $exitCode = $LASTEXITCODE
  } finally {
    Pop-Location
  }
} finally {
  Restore-Environment $previous $keys
}
exit $exitCode
