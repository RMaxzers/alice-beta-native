<#
.SYNOPSIS  Verified status. Every line comes from a real probe; nothing is reported HEALTHY without checking.
#>
. "$PSScriptRoot\_common.ps1"
$ok = 0; $bad = 0
function Line($label, $state, $detail) {
  $color = switch -Regex ($state) { '^HEALTHY|^READY|^OK' { 'Green' } '^DISABLED|^PENDING|^NOT_CONFIGURED|^CONFIGURED' { 'Yellow' } default { 'Red' } }
  Write-Host ("{0,-15}" -f "${label}:") -NoNewline; Write-Host ("{0,-16}" -f $state) -ForegroundColor $color -NoNewline; Write-Host " $detail"
  if ($color -eq 'Green') { $Script:ok++ } elseif ($color -eq 'Red') { $Script:bad++ }
}
function Get-Json($url) { try { Invoke-RestMethod $url -TimeoutSec 4 } catch { $null } }

Write-Host "`nALICE BETA 0.1`n==============" -ForegroundColor Cyan
$hz = Get-Json 'http://127.0.0.1:8000/healthz'
if (Test-Http 'http://127.0.0.1:8000/') { Line 'Alice UI' 'HEALTHY' 'http://127.0.0.1:8000/' } else { Line 'Alice UI' 'DOWN' 'http://127.0.0.1:8000/' }
if ($hz) { Line 'Alice API' 'HEALTHY' 'http://127.0.0.1:8000/api' } else { Line 'Alice API' 'DOWN' '' }
if ($hz -and $hz.router_ready) { Line 'Router' 'READY' "rules + semantic + classifier" } elseif ($hz) { Line 'Router' 'DEGRADED' 'rules only (embeddings unavailable)' } else { Line 'Router' 'DOWN' '' }

$v = Get-Json 'http://127.0.0.1:11434/api/version'
if ($v) {
  $tags = (Get-Json 'http://127.0.0.1:11434/api/tags').models.name -join ', '
  $ps = (Get-Json 'http://127.0.0.1:11434/api/ps').models | ForEach-Object { "$($_.name) ($([math]::Round($_.size_vram/1GB,1)) GB VRAM)" }
  Line 'Ollama' 'HEALTHY' "v$($v.version); loaded: $(if($ps){$ps -join ', '}else{'none'}); installed: $tags"
} else { Line 'Ollama' 'DOWN' 'http://127.0.0.1:11434' }

if (Test-Http 'http://127.0.0.1:6333/healthz') { Line 'Qdrant' 'HEALTHY' 'http://127.0.0.1:6333 (loopback)' } else { Line 'Qdrant' 'DOWN' '' }

$t = Get-Json 'http://127.0.0.1:9090/api/v1/targets'
if ($t) {
  $up = @($t.data.activeTargets | Where-Object health -eq 'up').Count; $all = @($t.data.activeTargets).Count
  $down = ($t.data.activeTargets | Where-Object health -ne 'up' | ForEach-Object { $_.labels.job }) -join ','
  Line 'Prometheus' $(if ($up -eq $all) { 'HEALTHY' } else { 'DEGRADED' }) "targets up $up/$all $(if($down){"(down: $down)"})"
} else { Line 'Prometheus' 'DOWN' '' }

$g = Get-Json 'http://127.0.0.1:3000/api/health'
if ($g -and $g.database -eq 'ok') { Line 'Grafana' 'HEALTHY' "http://127.0.0.1:3000/d/alice-overview (v$($g.version))" } else { Line 'Grafana' 'DOWN' '' }

if ($hz) {
  foreach ($k in 'hermes', 'openrouter', 'web', 'docker') {
    $s = $hz.integrations.$k
    Line (@{hermes='Hermes';openrouter='OpenRouter';web='Web search';docker='Docker'}[$k]) $s.state.ToUpper() $s.detail
  }
} else { Line 'OpenRouter' 'UNKNOWN' 'API down' }

$gpu = & nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits 2>$null
if ($LASTEXITCODE -eq 0 -and $gpu) { $f = $gpu.Split(',').Trim(); Line 'GPU' 'OK' "$($f[0]); VRAM $($f[1])/$($f[2]) MiB; util $($f[3])%; $($f[4])C" } else { Line 'GPU' 'NOT_DETECTED' 'nvidia-smi failed' }

$serve = (& tailscale serve status --json 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue)
$dns = (& tailscale status --json 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue).Self.DNSName
if ($serve -and $dns -and ($serve.TCP.PSObject.Properties.Name -contains '8443')) {
  $url = "https://$($dns.TrimEnd('.')):8443/"
  Line 'Remote access' 'CONFIGURED' "$url (tailnet only; external laptop test: see docs/REMOTE-DEMO.md)"
} else { Line 'Remote access' 'PENDING' 'tailscale serve :8443 not configured' }

$o = Get-CimInstance Win32_OperatingSystem
Write-Host ("`nRAM free {0:N1} / {1:N1} GB" -f ($o.FreePhysicalMemory / 1MB), ($o.TotalVisibleMemorySize / 1MB))
if ($bad -gt 0) { exit 1 }
