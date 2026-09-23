<#
.SYNOPSIS  Ejecuta las comprobaciones de Alice y genera un informe saneado en work\test-<fecha>\ (resumen en consola).
.DESCRIPTION
  Pasos (cada uno con timeout; un fallo no detiene los siguientes):
    pytest        uv/venv: python -m pytest -q  (tests\)
    router-eval   python -m tests.routing.eval_router  (usa Ollama; REESCRIBE docs\ROUTER-EVAL.md) - omitir con -SkipRouterEval
    status        Status-Alice.ps1 (sondas reales de todos los componentes)
    dashboard     Test-Dashboard.ps1 (cada consulta de ALICE / OVERVIEW contra Prometheus y Grafana)
    samples       Demo-Alice.ps1 (checksums de data\samples)
  Saneado: el valor de cualquier variable de .env con PASSWORD/SECRET/KEY/TOKEN en el nombre que aparezca en la salida se sustituye por <REDACTED>.
.OUTPUTS   exit 0 = todos PASS; 1 = algún FAIL/TIMEOUT.
#>
param([switch]$SkipRouterEval, [int]$TimeoutSec = 600)
. "$PSScriptRoot\_common.ps1"
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dir = Join-Path $Root "work\test-$stamp"
New-Item -ItemType Directory -Force $dir | Out-Null
$py = Join-Path $Root '.venv\Scripts\python.exe'
$pwsh = (Get-Process -Id $PID).Path
$envMap = Read-DotEnv
$secrets = $envMap.Keys | Where-Object { $_ -match 'PASSWORD|SECRET|KEY|TOKEN' } | ForEach-Object { $envMap[$_] } |
  Where-Object { $_ -and $_.Length -ge 6 } | Sort-Object Length -Descending

function Invoke-Step([string]$Name, [string]$Exe, [string[]]$ArgList, [int]$Timeout = $TimeoutSec) {
  $log = Join-Path $dir "$Name.log"
  Write-Host ("{0,-12} ... " -f $Name) -NoNewline
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $p = Start-Process $Exe -ArgumentList $ArgList -WorkingDirectory $Root -NoNewWindow -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
  $null = $p.Handle  # keep the handle so ExitCode is available after exit
  if ($p.WaitForExit($Timeout * 1000)) { $state = if ($p.ExitCode -eq 0) { 'PASS' } else { "FAIL (exit $($p.ExitCode))" } }
  else { & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null; $state = "TIMEOUT (${Timeout}s)" }
  # Sanitize: merge stderr, strip ANSI colours and any .env value.
  $text = (Get-Content $log, "$log.err" -Raw -ErrorAction SilentlyContinue) -join "`n"
  $text = $text -replace "`e\[[0-9;]*m", ''
  foreach ($s in $secrets) { $text = $text.Replace($s, '<REDACTED>') }
  Set-Content $log $text -Encoding utf8; Remove-Item "$log.err" -ErrorAction SilentlyContinue
  Write-Host ("{0} ({1:N0} s)" -f $state, $sw.Elapsed.TotalSeconds) -ForegroundColor $(if ($state -eq 'PASS') { 'Green' } else { 'Red' })
  [pscustomobject]@{ Step = $Name; Result = $state; Seconds = [int]$sw.Elapsed.TotalSeconds; Log = "$Name.log"; Tail = (($text -split "`n") | Where-Object { $_.Trim() } | Select-Object -Last 3) -join ' | ' }
}

$results = @()
$results += Invoke-Step 'pytest' $py @('-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests')
if ($SkipRouterEval) { $results += [pscustomobject]@{ Step = 'router-eval'; Result = 'SKIPPED'; Seconds = 0; Log = ''; Tail = '-SkipRouterEval' } }
else { $results += Invoke-Step 'router-eval' $py @('-m', 'tests.routing.eval_router') }
$results += Invoke-Step 'status' $pwsh @('-NoProfile', '-File', "`"$PSScriptRoot\Status-Alice.ps1`"") 60
$results += Invoke-Step 'dashboard' $pwsh @('-NoProfile', '-File', "`"$PSScriptRoot\Test-Dashboard.ps1`"") 180
$results += Invoke-Step 'samples' $pwsh @('-NoProfile', '-File', "`"$PSScriptRoot\Demo-Alice.ps1`"") 60

$commit = try { & git -C $Root rev-parse --short HEAD 2>$null } catch { '' }
$dirty = try { if (& git -C $Root status --porcelain 2>$null) { ' (con cambios sin commit)' } else { '' } } catch { '' }
$report = @("# Informe de pruebas Alice ($stamp)", '', "- Fecha: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))", "- Commit: $commit$dirty",
  "- Host: $env:COMPUTERNAME; PowerShell $($PSVersionTable.PSVersion); $(& $py --version 2>&1)", '',
  '| Paso | Resultado | s | Log | Últimas líneas |', '|---|---|---|---|---|')
$report += $results | ForEach-Object { "| $($_.Step) | $($_.Result) | $($_.Seconds) | $($_.Log) | $($_.Tail -replace '\|', '/') |" }
Set-Content (Join-Path $dir 'REPORT.md') $report -Encoding utf8

Write-Host "`nInforme: $(Join-Path $dir 'REPORT.md')"
$results | Format-Table Step, Result, Seconds -AutoSize | Out-String | Write-Host
if ($results | Where-Object { $_.Result -notin 'PASS', 'SKIPPED' }) { exit 1 }
