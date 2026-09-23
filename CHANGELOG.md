# Cambios

## 2026-09-23 · Rediseño y portada

- Tema «Nocturne»: fuentes Geist, Space Grotesk y Geist Mono incluidas en la app (sin CDN), superficies en capas, barra lateral con íconos y barra superior con el estado «Solo local».
- Portada animada con anime.js y mapa del mundo (d3-geo + world-atlas incluidos): arquitectura real con ubicaciones aproximadas.
- Pestaña «Inicio» con mapa en vivo: cada consulta real se anima según el proveedor que la atendió; contadores del día y últimas consultas.
- Observabilidad responde qué componente de Alice usa más RAM (memoria privada por proceso).
- Corregido: un p95 sin consultas (NaN) causaba HTTP 500; ahora es «sin datos».
- Corregido: `index.html` se quedaba en caché y ocultaba las versiones nuevas; ahora se revalida siempre y los assets con hash son inmutables.
- Corregido: los scripts podían perder el manifiesto de la API justo después de arrancarla y dejarla huérfana.
- Las fuentes `.woff2` se sirven como `font/woff2`.
## 0.1.0-beta.1 (sin publicar)

### Infraestructura y observabilidad
- Stack nativo de Windows con binarios fijados por SHA256: Qdrant 1.19.1 (servidor), Prometheus 3.14.0, Grafana 13.2.2, windows_exporter 0.31.8.
- Dashboard ALICE / OVERVIEW (uid `alice-overview`) versionado y provisionado con datasource de UID fijo `alice-prometheus`; `Test-Dashboard.ps1` verifica cada consulta en Prometheus y Grafana.
- windows_exporter con colectores `process` (filtrado a los binarios del stack) y `textfile` para `alice_native_process`.
- Manifiesto de procesos `storage\run\<nombre>.json` (PID, hora de inicio, ejecutable, logs); Stop-Alice verifica identidad y mata el árbol del proceso.
- Start-Alice espera el primer scrape de Prometheus; Status-Alice muestra `PENDING` en lugar de `0/0` y trata las integraciones opcionales no disponibles como aviso.
- Nuevos scripts: `Test-Alice.ps1`, `Test-Dashboard.ps1`, `Backup-Alice.ps1`, `Restore-Alice.ps1`, `Demo-Alice.ps1`.
- Opción `ALICE_GRAFANA_TRUSTED_ORIGINS` para el acceso Viewer de Grafana por la tailnet.

### Datos de demo
- `data/samples`: dataset sintético de demostración (PDF de 2 páginas, Markdown, CSV de inventario con `estado_soporte`, log con errores conocidos, hecho verificado) con `SHA256SUMS`.

### Documentación
- Documentación en español: STATUS, ARCHITECTURE, MIGRATION-WINDOWS, DOCKER-INTEGRATION, AGENT-PLAN, MODELS, CONFIGURATION, SECURITY, OBSERVABILITY, OPERATIONS, BACKUP-RESTORE, REMOTE-DEMO, DEMO, ROADMAP; ENVIRONMENT y DECISIONS traducidos (D13 y D14 añadidas). README en español y README.en.md.

### Aplicación (commits previos)
- API FastAPI con sesión/CSRF, router por reglas, similitud y clasificador, RAG, SQL, ledger de costes, política de egress, UI en español y batería de tests.
