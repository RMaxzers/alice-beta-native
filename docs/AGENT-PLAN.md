# Plan de agentes

Ejecución paralela (especificación §22). Cada agente es dueño de sus archivos; nadie edita archivos de otro sin pasar por el coordinador.

| Agente | Archivos propios | Tareas | Depende de | Terminado cuando | Resultado / pruebas |
|---|---|---|---|---|---|
| Coordinador | contratos compartidos, `.env.example`, `pyproject.toml`/`uv.lock`, integración y commits | Integrar, revisar privacidad/costes, pruebas conjuntas, pasos reales de cloud, Tailscale y Git (con consentimiento del usuario) | todos | Beta integrada, TEST-REPORT completo, repo privado publicado | En curso |
| Frontend | `apps/web/` | Pantallas, estados reales, integración API, privacidad en UI, demo | contratos de la API | Build servido por la API, recorrido de la demo en la UI | En curso |
| Backend / tests | `apps/api/`, `services/`, `packages/`, `tests/`, `docs/ROUTER-EVAL.md`, `docs/TEST-REPORT.md` | Routing, políticas, proveedores, RAG/SQL, correcciones del backend | Ollama, Qdrant | pytest verde, evaluación del router | 259 tests pasan (Test-Alice, 2026-09-22 23:51) |
| Infraestructura / observabilidad / docs | `scripts/windows/`, `infra/` (salvo `infra/bin`), `docs/` (salvo ROUTER-EVAL y TEST-REPORT), `data/samples/`, `README*.md`, `CHANGELOG.md` | Dashboard, scripts de operación, backup/restore, datos de demo, documentación | API de métricas, Prometheus, Grafana | Dashboard verificado consulta a consulta, backup→restore probado, docs §19 | Ver STATUS y OBSERVABILITY; 35 consultas sin error, restauración verificada 4/7/7 |

Reglas comunes: no imprimir secretos; no hacer commit ni push (solo el coordinador); no tocar Tailscale, firewall ni variables globales; limitar inferencias y builds simultáneos por los 16 GB de RAM; no abrir el mismo almacenamiento de Qdrant desde dos procesos.
