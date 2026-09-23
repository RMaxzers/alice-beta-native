# Observabilidad

Prometheus guarda las series; Grafana las muestra; Alice las consulta con plantillas PromQL de lectura. Todo en loopback.

## Fuentes (verificadas el 2026-09-22 contra `/api/v1/label/__name__/values` y cada `/metrics`)

| Job Prometheus | Target | Qué aporta |
|---|---|---|
| `alice` | 127.0.0.1:9101 | `alice_requests_total{route,provider,model_alias,status}`, histogramas `alice_request_duration_seconds{route,provider}`, `alice_queue_wait_seconds`, `alice_provider_request_duration_seconds{provider}`, `alice_rag_retrieval_duration_seconds`, `alice_routing_duration_seconds{decided_by}`; contadores `alice_provider_attempts_total`, `alice_provider_tokens_total`, `alice_provider_cost_usd_total`, `alice_errors_total`, `alice_egress_blocked_total`; gauges `alice_queue_depth`, `alice_dependency_up{dependency}`, `alice_gpu_*` (nvidia-smi, D12), `alice_ollama_models_installed`, `alice_ollama_model_loaded_vram_bytes{model}` |
| `windows` | 127.0.0.1:9182 | Colectores `cpu, memory, logical_disk, net, os, system, physical_disk, process, textfile`. `process` solo incluye los binarios del stack (`python, ollama, llama-server, qdrant, prometheus, grafana, gpx_*, windows_exporter*`). `textfile` publica `alice_native_process{component,owned,process_id}` |
| `prometheus`, `qdrant`, `grafana` | 9090, 6333, 3000 | Métricas propias y `up` |

Los contadores con etiquetas (`alice_errors_total`, `alice_egress_blocked_total`, `alice_provider_cost_usd_total`, `alice_requests_total{status!="ok"}`) no existen hasta su primer evento. En el dashboard eso se ve como «sin datos», nunca como cero.

## Procesos nativos de Alice

`Status-Alice.ps1` (y por tanto `Start-Alice.ps1` y `Test-Alice.ps1`) reescribe `storage\run\textfile\alice_processes.prom` con los PID de los manifiestos propios y sus hijos directos, y el PID de Ollama como `owned="false"`. Grafana hace el join:

```promql
sum by (component) (windows_process_working_set_private_bytes * on(process_id) group_left(component) alice_native_process)
```

Límite: si un proceso crea hijos nuevos (por ejemplo `llama-server.exe` al cargar un modelo) no aparecen hasta el siguiente `Status-Alice.ps1`. Los plugins `gpx_*` de Grafana sí se cuentan dentro de `grafana` (13 procesos; unos 620 MB de working set medidos en un juego de plugins huérfano).

## Dashboard ALICE / OVERVIEW

Archivo versionado `infra/grafana/dashboards/alice-overview.json`, uid `alice-overview`, carpeta ALICE, datasource uid fijo `alice-prometheus` (`infra/grafana/provisioning/datasources/prometheus.yaml`). El proveedor de ficheros no permite edición desde la UI (`allowUiUpdates: false`) y Grafana recarga el JSON sin reiniciar. Variable `$interval` (1m, 5m, 15m, 30m, 1h; por defecto 5m). Zona horaria America/Santiago. Refresco 30 s.

Filas: salud (dependencias + scrapes), host Windows (CPU % del host, RAM, disco C:), GPU (utilización, VRAM, temperatura, VRAM por modelo), peticiones (por ruta, distribución, local vs cloud), latencia (p50/p95 con `histogram_quantile` sobre `rate` de buckets; p95 por etapa), errores y cola, tokens y costes (solo coste reportado; texto que explica estimado/desconocido), procesos nativos (memoria, CPU % del host, procesos vivos) y Docker (deshabilitado, texto explicativo, sin datos simulados).

### Verificación de cada consulta

`scripts\windows\Test-Dashboard.ps1` ejecuta cada expresión del JSON contra la API de Prometheus (consulta instantánea) y contra Grafana `/api/ds/query` con el datasource provisionado (credencial admin leída de `.env`, nunca impresa). Resultado del 2026-09-22 23:41 (tras cargar la demo y una consulta local):

| Resultado | Consultas |
|---|---|
| DATA | 30 de 35 |
| NO_DATA deliberado | 5: cloud en «local vs cloud» (sin llamadas cloud), «sin proveedor», errores/no OK/egress bloqueado (ningún evento), coste reportado (sin llamadas cloud) |
| ERROR | 0 |

Segunda ejecución (23:51, dentro de `Test-Alice.ps1`): 0 errores; en consulta instantánea 25 con datos y 10 sin datos (sin peticiones en los últimos 5 min: latencias y p95 vacías), y en rango de 30 min Grafana devolvió datos también para p50/p95. Con la API recién arrancada y sin peticiones, los paneles de latencia p50/p95 y p95 por etapa también muestran «sin datos».

## Diagnóstico de «targets 0/0» y «4/5 (down: alice)»

- `0/0`: `Status-Alice.ps1` se ejecutaba justo después de `/-/ready`, antes de que Prometheus cargara los targets. `Start-Alice.ps1` ahora espera (máx. 40 s) a que todos los targets estén `up` (así un target recién reiniciado no aparece como `down` obsoleto); `Status-Alice.ps1` muestra `PENDING` si aún no hay targets o alguno está en `unknown`. Probado reiniciando Prometheus (5/5 a los 21 s) y windows_exporter (5/5, exit 0).
- `4/5 (down: alice)`: el primer scrape llegó antes de que la API abriera 9101 (la API tarda en arrancar por el calentamiento del router). Se recupera en el siguiente scrape. Además `Stop-Alice.ps1` mataba solo el proceso padre: el lanzador del venv podía dejar huérfano el hijo que ocupa 8000/9101, y Grafana dejaba sus 13 procesos de plugins `gpx_*`. Se encontró y eliminó un juego huérfano de 14 procesos (unos 620 MB) de un Grafana anterior. Ahora `Stop-Alice.ps1` mata el árbol.

## Consultas de Alice

`PrometheusAdapter` usa un catálogo fijo de consultas (ver `services/observability/prometheus.py`). Retención de Prometheus: 7 días o 2 GB. Scrape cada 15 s.
