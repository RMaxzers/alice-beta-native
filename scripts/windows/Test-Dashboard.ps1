<#
.SYNOPSIS  Comprueba cada consulta del dashboard ALICE / OVERVIEW contra Prometheus y vía Grafana (/api/ds/query).
           Resultado por consulta: DATA (series con valores), NO_DATA («sin datos» deliberado) o ERROR.
           La contraseña de admin de Grafana se lee de .env dentro del script y nunca se imprime.
.OUTPUTS   Tabla en consola; exit 1 si alguna consulta devuelve ERROR o el dashboard no está provisionado.
#>
param([string]$Interval = '5m', [ValidatePattern('^\d+m$')][string]$Range = '30m')
. "$PSScriptRoot\_common.ps1"
$dashFile = Join-Path $Root 'infra\grafana\dashboards\alice-overview.json'
$dash = Get-Content $dashFile -Raw -Encoding utf8 | ConvertFrom-Json
$cfg = Read-DotEnv
$auth = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("admin:$($cfg['GRAFANA_ADMIN_PASSWORD'])")) }
$fail = 0

try {
  $g = Invoke-RestMethod 'http://127.0.0.1:3000/api/dashboards/uid/alice-overview' -Headers $auth -TimeoutSec 10
  Write-Host "Grafana: dashboard '$($g.dashboard.title)' provisionado (version $($g.dashboard.version), carpeta $($g.meta.folderTitle))"
} catch { Write-Host "Grafana: dashboard alice-overview NO encontrado ($($_.Exception.Message))" -ForegroundColor Red; $fail++ }

$rangeSec = [int]$Range.TrimEnd('m') * 60
$now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$rows = foreach ($p in $dash.panels | Where-Object { $_.targets }) {
  foreach ($t in $p.targets) {
    $expr = $t.expr.Replace('$__rate_interval', '1m').Replace('$__range', $Range).Replace('$interval', $Interval)
    # Prometheus (instant query)
    try {
      $r = Invoke-RestMethod 'http://127.0.0.1:9090/api/v1/query' -Method Post -Body @{ query = $expr } -TimeoutSec 15
      $vals = @($r.data.result | Where-Object { $_.value[1] -notin 'NaN', '+Inf', '-Inf' })
      $prom = if ($vals.Count) { "DATA($($vals.Count))" } else { 'NO_DATA' }
    } catch { $prom = 'ERROR'; $fail++ }
    # Grafana datasource proxy (same query as the panel, through the provisioned datasource UID)
    try {
      $body = @{ from = "$($now - $rangeSec * 1000)"; to = "$now"; queries = @(@{ refId = 'A'; datasource = @{ uid = 'alice-prometheus'; type = 'prometheus' }
                 expr = $expr; instant = [bool]$t.instant; range = -not [bool]$t.instant; intervalMs = 15000; maxDataPoints = 200 }) } | ConvertTo-Json -Depth 6
      $q = Invoke-RestMethod 'http://127.0.0.1:3000/api/ds/query' -Method Post -Headers $auth -Body $body -ContentType 'application/json' -TimeoutSec 20
      $res = $q.results.A
      if ($res.error) { $graf = 'ERROR'; $fail++ }
      else {
        $n = @($res.frames | Where-Object { $_.data.values -and @($_.data.values[-1] | Where-Object { $_ -ne $null }).Count }).Count
        $graf = if ($n) { "DATA($n)" } else { 'NO_DATA' }
      }
    } catch { $graf = 'ERROR'; $fail++ }
    [pscustomobject]@{ Panel = $p.title; Ref = $t.refId; Prometheus = $prom; Grafana = $graf }
  }
}
$rows | Format-Table -AutoSize -Wrap | Out-String -Width 220 | Write-Host
Write-Host ("Consultas: {0}; DATA: {1}; NO_DATA: {2}; ERROR: {3}" -f $rows.Count, @($rows | Where-Object Prometheus -like 'DATA*').Count,
  @($rows | Where-Object Prometheus -eq 'NO_DATA').Count, $fail)
if ($fail) { exit 1 }
