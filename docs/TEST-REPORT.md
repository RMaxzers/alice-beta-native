# Informe de pruebas · Alice Beta 0.1

Fecha: 2026-09-22/23 · Tag: `v0.1.0-beta.1` · Equipo: el descrito en `ENVIRONMENT.md` · Datos: solo el dataset sintético de `data/samples/`.

Resultado posible por fila: PASS, FAIL o PENDIENTE (no ejecutado). Nada marcado PASS se probó solo con mocks salvo que se indique.

## Resumen

| Área (§21.1) | Resultado | Evidencia |
|---|---|---|
| Continuación | PASS | Trabajo previo conservado en el commit `5843cb2`; tres agentes con archivos propios (`AGENT-PLAN.md`), integración y commits por el coordinador |
| Instalación | PASS | `Stop-Alice.ps1` completo → `Start-Alice.ps1`: todos los componentes HEALTHY, 5/5 targets, todo en loopback, sin WSL/Hyper-V/Docker |
| Local | PASS | LOCAL_SIMPLE y LOCAL_CODE con `qwen3:4b-instruct-2507-q4_K_M` en GPU; tiempos en «Rendimiento» |
| Routing | PASS | 52/52 (100 %), 8 decididos por el clasificador, 44 por reglas; `ROUTER-EVAL.md` del 2026-09-23 00:13 |
| RAG | PASS | Citas reales (PDF «página 2», Markdown «sección: Reserva de direcciones»); persistencia tras reinicio; «no encontré evidencia» cuando falta el dato (test de integración + prueba en vivo) |
| Vector store | PASS | Qdrant servidor nativo (sin Docker); backup → restauración en destino temporal con conteos cuadrados |
| Ingestión | PASS | Tipo inválido, tamaño, duplicado, PDF sin texto («requiere OCR»), fallo parcial y borrado completo (`tests/unit/test_ingestion.py`) |
| SQL | PASS | «¿Cuántos activos… fuera de soporte?» → 4 de 12 con la consulta visible; 20 ataques bloqueados (`test_sql.py`) |
| Cloud | PENDIENTE | La llamada real a OpenRouter no se ejecutó: la bloqueó el filtro de permisos por ser una transacción de pago. Clave ausente y errores cubiertos con fakes |
| Costes | PASS (fakes) | Reserva atómica, 40 reservas concurrentes contra el límite diario, coste desconocido ≠ 0 (`test_ledger.py`) |
| Privacidad | PASS | Los 10 casos de §21.2 con receptor de red controlado (`test_privacy_egress.py`); en vivo, un pedido PRIVATE a cloud devolvió `authorization_required` y no salió nada |
| Docker desacoplado | PASS (fixtures) | El núcleo funciona sin daemon; adapter y allowlist probados con fixtures rotulados (`test_docker_adapter.py`) |
| Docker real | PENDIENTE | Sin daemon ni host autorizado |
| Observabilidad | PASS | Dashboard ALICE / OVERVIEW: 35 consultas, 0 errores; respuestas de Alice con fuente, intervalo y edad de la muestra |
| Web/finanzas | PENDIENTE | Tavily no se llamó en real; SSRF probado (`test_web_ssrf.py`, DNS falso) |
| Seguridad web | PASS | Sesión, CSRF, Origin, path traversal, aislamiento entre usuarios, throttle de login (también rotando X-Forwarded-For), cabeceras (`test_api_security.py`) |
| Remoto | PARCIAL | Tailscale Serve `:8443` aplicado y probado desde el propio PC por la URL de la tailnet (ver abajo). Falta la prueba desde el laptop en otra red |
| Backup | PASS | `Backup-Alice.ps1` en modo por defecto (detiene la API y la reanuda): integridad OK, 11 archivos. Restauración real en destino temporal verificada por el agente de infraestructura |
| Git | PASS | Escaneo del historial completo (8 commits, 162 blobs): ningún valor de `.env` ni patrón de clave. Repositorio privado verificado antes y después del push |

## Suite automática

`pytest tests -q` → **266 passed** (0 failed, 0 skipped). Incluye 1 test de integración real (bge-m3, qwen3 y Qdrant, colección temporal borrada al terminar).

## Recorrido de demo en vivo (2026-09-23, API en 127.0.0.1:8000)

| Paso | Ruta obtenida | Resultado |
|---|---|---|
| «Explícame DHCP en pocas palabras» | LOCAL_SIMPLE (clasificador) | Respuesta correcta, qwen3 local |
| «Genera una función en Python que valide direcciones IPv4» | LOCAL_CODE (reglas) | Código generado, no ejecutado |
| «¿Qué VLAN usa la red de invitados y cuánto dura su arrendamiento DHCP?» | LOCAL_RAG | «VLAN 30 … 4 horas [1]», cita del PDF página 2 |
| «¿Qué rango está reservado para infraestructura?» | LOCAL_RAG (sonda semántica) | 192.168.10.1–192.168.10.49, cita de la sección «Reserva de direcciones». Antes de la corrección `4895130` iba a LOCAL_SIMPLE y respondía sin documentos |
| «¿Cuántos activos del inventario están fuera de soporte?» | STRUCTURED_QUERY | 4 filas, consulta SQL parametrizada visible |
| «¿Qué componente de Alice usa más memoria ahora?» | OBSERVABILITY | Datos reales de windows_exporter con unidades |
| «Dame los últimos errores del log cargado» | LOG_ANALYSIS | 3 ERROR / 2 WARN / 5 INFO, error más frecuente agrupado |
| «¿Qué cambió durante mi última consulta?» | OBSERVABILITY | Ventana de la consulta y aviso honesto de que duró menos que el intervalo de muestreo |
| Pedido PRIVATE a cloud | CLOUD_CHEAP (policy) | `authorization_required` con destinatarios, modelo y vista previa; no se aprobó |
| «¿Cuántas consultas fueron locales y cuánto costó el cloud hoy?» | OBSERVABILITY | Conteo real, coste cloud USD 0,0000 |
| Consulta PUBLIC a cloud / investigación web | — | PENDIENTE (sin llamada real) |

## Acceso por la tailnet (desde este PC, `https://eva01.tail3f8e85.ts.net:8443`)

UI 200; login 200 con cookie `Secure`; `/api/system` 200 tras el login; chat por streaming 200. Ocultos: `/healthz`, `/metrics`, `/docs` y `/openapi.json` dan 404, y `/api/documents` sin sesión da 401. Por la IP de la tailnet quedan bloqueados Qdrant, Prometheus, Grafana y las métricas en 9101. **Ollama (11434) sí responde por la IP de la tailnet**: ver «Límites».

## Rendimiento observado

- Generación de Ollama (medida por el agente de infraestructura): en frío 6,4 s (5,8 s de carga); en caliente 0,5–0,8 s para una respuesta corta, 71–94 tok/s.
- Extremo a extremo por la API, con bge-m3 y qwen3 cargados y otras aplicaciones abiertas: 18–23 s en LOCAL_SIMPLE/LOCAL_RAG con clasificador; 2,8–6 s cuando decide una regla; menos de 0,2 s en observabilidad. La VRAM estaba en 7,4 de 8 GB y la RAM libre en 2,2–2,5 GB, así que la diferencia con la generación aislada probablemente viene de la presión de memoria y la carga del clasificador. No se midió p50/p95 con muestras suficientes ni la sesión sostenida de 30 min (PENDIENTE).

## Límites de esta prueba

- Pendientes: llamada real a OpenRouter y a Tavily; prueba desde el laptop fuera de la LAN; acceso Viewer a Grafana por la tailnet (`:8444` no aplicado); sesión sostenida de 30 min; arranque tras reiniciar el PC; UI con sesión iniciada en un navegador real (solo se comprobó por HTTP y la pantalla de login).
- Ollama sigue escuchando en todas las interfaces porque la app tiene activado «Expose Ollama to the network». La variable `OLLAMA_HOST=127.0.0.1:11434` ya está a nivel de usuario, pero la opción de la app la anula.
- Estabilidad del equipo: 6 reinicios Kernel-Power 41 en 14 días (ver `ENVIRONMENT.md`).
