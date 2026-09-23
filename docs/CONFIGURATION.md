# Configuración

Fuente: `apps/api/config.py` (clase `Settings`, pydantic-settings) lee `.env` en la raíz del proyecto; las variables de entorno del proceso tienen prioridad. `.env.example` lista los nombres con valores ficticios. Aquí no hay valores reales. Las variables del backend no se exponen al frontend.

| Variable | Defecto en código | Uso |
|---|---|---|
| `ALICE_ENV` | `beta` | Nombre del entorno |
| `ALICE_TIMEZONE` | `America/Santiago` | Zona para presentar fechas y el día contable del ledger |
| `ALICE_HOST` / `ALICE_PORT` | `127.0.0.1` / `8000` | Entrada de UI + API (Start-Alice fija los mismos valores en la línea de uvicorn) |
| `ALICE_METRICS_PORT` | `9101` | `/metrics` en loopback (D9) |
| `ALICE_PUBLIC_ORIGIN` | vacío | Origen HTTPS de la tailnet (`https://<nodo>.<tailnet>.ts.net:8443`) |
| `ALICE_USERNAME` | `admin` | Usuario de la UI |
| `ALICE_PASSWORD` | vacío (secreto) | Contraseña de la UI; Setup la genera |
| `ALICE_SESSION_SECRET` | vacío (secreto) | Firma de cookies de sesión; Setup la genera |
| `ALICE_LOCAL_ONLY` | `false` | Si es `true`, ningún egress cloud |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama |
| `ALICE_CLOUD_ENABLED` | `true` | Permite rutas cloud (siempre sujetas a política de egress) |
| `OPENROUTER_API_KEY` | vacío (secreto) | OpenRouter |
| `ALICE_BUDGET_PER_REQUEST_USD` / `ALICE_BUDGET_DAILY_USD` | `0.05` / `1.00` | Presupuesto (D7) |
| `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | vacío (secretos) | Proveedores futuros, no habilitados |
| `TAVILY_API_KEY` | vacío (secreto) | Búsqueda web |
| `QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant servidor (modo activo) |
| `PROMETHEUS_URL` | `http://127.0.0.1:9090` | PrometheusAdapter |
| `ALICE_GRAFANA_LOCAL_URL` | `http://127.0.0.1:3000` | Grafana local (enlace y health) |
| `GRAFANA_EXTERNAL_ENABLED` | `false` | Adapter de Grafana externo |
| `GRAFANA_URL` / `GRAFANA_SERVICE_ACCOUNT_TOKEN` | vacío | Solo para el Grafana externo |
| `HERMES_ENABLED` / `HERMES_API_URL` | `false` / `http://127.0.0.1:8642` | HermesAdapter (D10) |
| `DOCKER_ENABLED` / `DOCKER_ALLOWED_CONTAINERS` | `false` / `alice-qdrant,alice-prometheus,alice-grafana` | DockerAdapter (D2) |
| `EMAIL_ENABLED`, `NOTEBOOKLM_ENABLED`, `LOKI_ENABLED` | `false` | Integraciones opcionales fuera del núcleo |
| `DATA_DIR` / `STORAGE_DIR` / `LOGS_DIR` | `<raíz>\data`, `<raíz>\storage`, `<raíz>\logs` | Raíces de datos (no están en `.env.example`) |
| `MAX_UPLOAD_MB` / `MAX_PDF_PAGES` | `50` / `1000` | Límites de ingestión (no están en `.env.example`) |

Rutas derivadas: `storage\sqlite\alice.db` (operación) y `storage\sqlite\tables.db` (tablas importadas).

## Solo para los scripts de Windows (no los lee la API)

| Variable | Uso |
|---|---|
| `GRAFANA_ADMIN_PASSWORD` (secreto) | Admin local de Grafana: provisioning, creación del Viewer, `Test-Dashboard.ps1` |
| `GRAFANA_VIEWER_PASSWORD` (secreto) | Usuario `viewer` de Grafana para la demo remota |
| `ALICE_GRAFANA_TRUSTED_ORIGINS` (opcional, no está en `.env.example`) | `host:puerto` de la entrada Serve de Grafana; se pasa como `GF_SECURITY_CSRF_TRUSTED_ORIGINS` (ver REMOTE-DEMO) |

## Configuración fija en archivos versionados

- `infra/prometheus/prometheus.yml`: scrape cada 15 s de 5 jobs. Retención 7 días / 2 GB (argumentos en Start-Alice).
- `infra/grafana/provisioning/`: datasource `alice-prometheus`, proveedor de dashboards (carpeta ALICE, sin edición desde UI).
- `config/models/aliases.yaml`: alias de modelos y ruta → alias.
- `scripts/windows/_common.ps1`: versiones y SHA256 de los binarios nativos.

Diferencias con el contrato de la especificación §20.1: no existen `ALICE_RUNTIME`, `ALICE_DATA_DIR`, `ALICE_VECTORSTORE_MODE`, `QDRANT_LOCAL_PATH` ni `ALICE_DOCKER_BROKER_URL`; el modo del vector store es implícitamente `server`. Ver ROADMAP.
