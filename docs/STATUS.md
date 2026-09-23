# Estado de Alice Beta 0.1

Actualizado: 2026-09-22 23:50 (agente de infraestructura). Solo hechos comprobados; lo no probado figura como pendiente.

## Funciona (verificado)

- Stack nativo en loopback arrancado por `Start-Alice.ps1`: API + UI (8000), métricas (9101), Qdrant 1.19.1 servidor (6333), windows_exporter 0.31.8 (9182), Prometheus 3.14.0 (9090, 5/5 targets up), Grafana 13.2.2 (3000). Ollama 0.34.3 reutilizado.
- Dashboard ALICE / OVERVIEW (uid `alice-overview`) provisionado desde `infra/grafana/dashboards/alice-overview.json`; 35 consultas comprobadas en Prometheus y Grafana, 0 errores; las que no tienen datos muestran «sin datos» (cuántas depende de la actividad reciente). El usuario `viewer` lo lee sin poder editarlo; el acceso anónimo devuelve 401.
- Procesos nativos de Alice visibles en Grafana (memoria, CPU % del host, procesos vivos) mediante manifiestos con PID + hora de inicio + ejecutable.
- Scripts `Test-Alice`, `Test-Dashboard`, `Backup-Alice`, `Restore-Alice`, `Demo-Alice`; `Stop-Alice` mata el árbol del proceso y verifica identidad.
- Backup `-Online` → restauración en un destino temporal con espacios: 4 documentos, 7 fragmentos, 7 puntos Qdrant, sin originales ausentes. Salvaguardas de restauración probadas.
- Dataset sintético de demostración cargado (4 documentos `ready` + 1 hecho verificado); consulta local de humo por LOCAL_SIMPLE en 12,1 s.
- `Test-Alice.ps1 -SkipRouterEval` (2026-09-22 23:51): pytest 259 passed, Status, Dashboard y checksums de la demo en PASS; informe en `work\test-20260922-235120\REPORT.md`.

## Pendiente

- Tailscale Serve `https=8443 -> 127.0.0.1:8000` y acceso Viewer de Grafana (comandos en REMOTE-DEMO); prueba desde el laptop en otra red; ACL/grants.
- Llamada real a OpenRouter y Tavily (Status: `CONFIGURED_NOT_TESTED`).
- Backup en modo por defecto (offline, detiene y reanuda la API).
- Evaluación del router dentro de `Test-Alice.ps1` (se omitió con `-SkipRouterEval` porque reescribe `docs/ROUTER-EVAL.md`).
- Arranque tras reinicio del PC no probado.
- Modo Qdrant embebido (no implementado; el activo es servidor nativo).

## Bloqueado

- Docker: sin daemon en este host (D1/D2). Adapter preparado; host pendiente de que el usuario autorice uno (DOCKER-INTEGRATION).

## Riesgos abiertos

- Ollama escucha en `[::]:11434` (todas las interfaces). Corrección: `OLLAMA_HOST=127.0.0.1:11434` a nivel de usuario y reiniciar la app de Ollama (SECURITY). No aplicada.
- 6 reinicios Kernel-Power 41 en 14 días; RAM libre entre 1,4 y 3,1 GB con el stack y dos modelos cargados.

## Siguiente acción concreta

El coordinador, con consentimiento del usuario: aplicar la corrección de `OLLAMA_HOST`, ejecutar `tailscale serve --bg --https=8443 http://127.0.0.1:8000` y seguir la sección 5 de REMOTE-DEMO desde el laptop.
