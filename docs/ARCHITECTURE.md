# Arquitectura (tal como está instalada)

Perfil `windows-native`: todo corre como procesos nativos de Windows 11 en el PC `eva01`, sin WSL2, Hyper-V ni Docker (decisión D1). Estado verificado el 2026-09-22.

## Componentes y puertos

| Componente | Versión | Proceso | Escucha | Dueño del proceso |
|---|---|---|---|---|
| Alice API + UI | 0.1.0b1 (Python 3.12, FastAPI/uvicorn, 1 worker) | `.venv\Scripts\python.exe` (lanzador) + hijo `python.exe` de uv | 127.0.0.1:8000 (UI + `/api`) | Scripts de Alice |
| Métricas de Alice | prometheus-client | mismo proceso que la API | 127.0.0.1:9101 (`/metrics`, D9) | Scripts de Alice |
| Ollama | 0.34.3 | `ollama.exe` + `llama-server.exe` por modelo cargado | `[::]:11434` (todas las interfaces, ver SECURITY) | App de bandeja de Ollama (reutilizado; Alice no lo arranca ni lo para) |
| Qdrant (modo **servidor**) | 1.19.1 | `infra\bin\qdrant-1.19.1\qdrant.exe` | 127.0.0.1:6333 HTTP, 127.0.0.1:6334 gRPC | Scripts de Alice |
| windows_exporter | 0.31.8 | `infra\bin\winexp-0.31.8\...exe` | 127.0.0.1:9182 | Scripts de Alice |
| Prometheus | 3.14.0 | `infra\bin\prometheus-3.14.0\...\prometheus.exe` | 127.0.0.1:9090 | Scripts de Alice |
| Grafana OSS | 13.2.2 | `infra\bin\grafana-13.2.2\...\grafana.exe` (+ procesos `gpx_*` de plugins) | 127.0.0.1:3000 | Scripts de Alice |
| Tailscale | 1.102.2 | servicio de Windows | 443 en la IP de la tailnet | Sistema (preexistente) |

El vector store activo es Qdrant **servidor nativo** (`QDRANT_URL=http://127.0.0.1:6333`), colección `alice_chunks` (1024 dimensiones, coseno). No depende de Docker. El modo embebido (`QdrantClient(path=...)`) no está implementado en esta beta; ver ROADMAP.

## Flujo

```text
Navegador (local o laptop por la tailnet)
  -> Tailscale Serve https :8443 (PENDIENTE, D8) -> 127.0.0.1:8000
  -> Alice API: sesión + CSRF -> políticas -> router (reglas -> semántico -> clasificador qwen3)
       -> LOCAL_*      -> Ollama qwen3:4b-instruct-2507-q4_K_M
       -> LOCAL_RAG    -> embeddings bge-m3 (Ollama) -> Qdrant alice_chunks; metadatos y fragmentos en SQLite
       -> STRUCTURED   -> SQLite tables.db (consultas SQL restringidas)
       -> CLOUD_*/WEB  -> OpenRouter / Tavily (con autorización de egress y presupuesto)
       -> OBSERVABILITY-> Prometheus 127.0.0.1:9090 + health checks
Prometheus <- scrape 15 s: alice :9101, windows :9182, prometheus :9090, qdrant :6333/metrics, grafana :3000/metrics
Grafana (datasource uid alice-prometheus) -> dashboard ALICE / OVERVIEW (uid alice-overview)
```

## Almacenamiento

| Ruta | Contenido | En Git |
|---|---|---|
| `storage\sqlite\alice.db` | catálogo de documentos, fragmentos, hechos, peticiones, ledger, auditoría (WAL) | No |
| `storage\sqlite\tables.db` | tablas importadas de CSV/XLSX | No |
| `storage\qdrant\data`, `storage\qdrant\snapshots` | datos del servidor Qdrant | No |
| `storage\prometheus` | TSDB (7 días / 2 GB) | No |
| `storage\grafana` | base de datos de Grafana (usuarios, sesiones) | No |
| `storage\run\*.json` | manifiestos de procesos propios (PID, hora de inicio, ejecutable, logs) | No |
| `storage\run\textfile\alice_processes.prom` | métrica `alice_native_process` para windows_exporter | No |
| `data\raw`, `data\processed`, `data\verified`, `data\quarantine` | originales y derivados de la ingestión | No |
| `data\samples` | dataset sintético de demostración | Sí |
| `logs\` | stdout/stderr de cada proceso propio, logs de Grafana | No |
| `backups\` | copias de `Backup-Alice.ps1` | No |
| `infra\bin\` | binarios fijados con SHA256 (Setup-Alice.ps1) | No |

## Matriz de conexiones

Todas las conexiones son locales por loopback salvo las marcadas. Verificado con `Get-NetTCPConnection` y los targets de Prometheus el 2026-09-22.

| Origen | Destino | Permitido | Motivo |
|---|---|---|---|
| Navegador local | 127.0.0.1:8000 | Sí | UI + API |
| Laptop por tailnet | https://eva01.tail3f8e85.ts.net:8443 -> 127.0.0.1:8000 | PENDIENTE (D8) | Demo remota; la API responde 404 a rutas fuera de `/`, `/assets/`, `/api/` cuando la petición llega por el proxy (según `apps/api/security.py`; no probado aún a través de Serve) |
| Laptop por tailnet | Grafana Viewer | PENDIENTE | Ver REMOTE-DEMO |
| Alice API | Ollama 127.0.0.1:11434 | Sí | Generación y embeddings |
| Alice API | Qdrant 127.0.0.1:6333 | Sí | Vector store |
| Alice API | Prometheus 127.0.0.1:9090, Grafana 127.0.0.1:3000, windows_exporter 127.0.0.1:9182 | Sí | Consultas de observabilidad y health checks |
| Alice API | openrouter.ai, api.tavily.com (Internet) | Sí, con política de egress y presupuesto | Cloud autorizado |
| Prometheus | 9101, 9182, 9090, 6333, 3000 en 127.0.0.1 | Sí | Scrape |
| Grafana | Prometheus 127.0.0.1:9090 | Sí | Datasource |
| Cualquier equipo de la LAN | 11434 (Ollama) | Hoy **sí** (binding `::`), no deseado | Corregir con `OLLAMA_HOST`, ver SECURITY |
| Cualquier equipo de la LAN | 8000, 9101, 6333, 9182, 9090, 3000 | No (loopback) | |

## Supervisión de procesos

Modo elegido: procesos gestionados por scripts (sin servicios de Windows ni tareas programadas). `Start-Alice.ps1` arranca solo lo que falta, en orden, y guarda un manifiesto por proceso. `Stop-Alice.ps1` para únicamente procesos cuyo PID, hora de inicio y ejecutable coinciden con su manifiesto y mata su árbol (el `python.exe` del venv es un lanzador cuyo hijo ejecuta la API). No arranca tras reiniciar el PC: hay que ejecutar `Start-Alice.ps1` después de iniciar sesión. Ver OPERATIONS.
