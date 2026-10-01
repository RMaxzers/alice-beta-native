# CODEX_STATUS · alice-next-20260928-01 · actualización 2026-09-30

Único escritor: Codex. Rama `feat/alice-core-cli`, worktree `C:\Users\cuent\alice-core-codex`, base `bc37fd445f44b3f4ac9b5a68e6c7692351cd2eb4`. Los tres commits de producto son locales y listos para que Claude los integre. No se arrancaron Alice ni los servicios de la instalación activa.

| ID | Alcance | Estado | Commit | Evidencia |
|---|---|---|---|---|
| CORE-00 | Contrato v1 y coordinación | validada | — | Claude aceptó v1; API_CONTRACT.md está actualizado y sincronizado. |
| CORE-01 | SQLite, sesiones, privacidad y conversaciones | lista_para_integrar | `8746bfa` | Migraciones aditivas, aislamiento por usuario, idempotencia, streaming NDJSON y persistencia de `sources`/`operation_ids`; suite completa verde. |
| CORE-02 | Backup/restore de Hindsight PostgreSQL y validación de destinos | lista_para_integrar | `ed3cc5e` | Roundtrip real PostgreSQL 18.1 en clusters y tablas sintéticas aisladas; scripts PowerShell parsean. |
| CORE-03 | CLI Python | lista_para_integrar | `333a170` | Tests Windows/DPAPI verdes; instalación aislada con uv y `alice --help` correctos. |
| CORE-04 | Acciones seguras de archivo y API | lista_para_integrar | `8746bfa` | Creación exclusiva, raíz configurada, protección frente a junctions/TOCTOU, verificación SHA-256 y recuperación de operaciones; suite completa verde. |
| CORE-05 | Prueba UI/API e integración en `alice-integration` | pendiente | — | Claude debe probar la UI contra API `:8100`, integrar estos commits y registrar el SHA combinado. |

## Respuestas R-01–R-06

- R-01: los eventos `action` incluyen el objeto público en ambos campos `action` y `file_action`.
- R-02: `GET /api/file-actions` admite filtros por `conversation_id`; el servidor limita `limit` a 1–200.
- R-03: los mensajes persistidos incluyen `sources` y `operation_ids` al reabrir conversaciones.
- R-04: `Restore-Alice.ps1` normaliza la ruta final y rechaza junctions/reparse points y destinos iguales o interiores a cualquier instalación/worktree conocido.
- R-05: `Backup-Alice.ps1 -SkipMemory` avisa en amarillo y deja `recoverable=false`.
- R-06: el contrato documenta reintentos de autorización con un `client_request_id` nuevo y ausencia de `done` para turnos `failed`/`awaiting_authorization`.

## Verificación

- Python 3.12.14, `pytest -q -m 'not integration' --tb=short -p no:cacheprovider`: **465 passed, 2 skipped, 1 deselected, 2 warnings**.
- `tests/security/test_file_actions.py tests/unit/test_cli.py`: **32 passed**.
- `tests/unit/test_backup_memory.py::test_real_postgres_snapshot_and_isolated_restore`: **1 passed** con PostgreSQL 18.1, dos clusters temporales y datos sintéticos. No se conectó a la instancia real de Hindsight.
- `uv tool install --python 3.12 .\clients\cli` en directorios aislados de `work/`, seguido de `alice --help`: correcto.
- Análisis de sintaxis de `Backup-Alice.ps1` y `Restore-Alice.ps1`: correcto. `git diff --check`: limpio.

La ejecución dentro del sandbox tuvo fallos de permisos para handles de Windows y DPAPI; los tests afectados pasaron al repetirse en el contexto normal de Windows. No se probó una copia offline completa contra servicios Alice, el login de la CLI contra API, Tailscale, ni el stack combinado/UI en `:8100`.

## Siguiente trabajo de Claude

1. Integrar `8746bfa`, `333a170` y `ed3cc5e` en `alice-integration`.
2. Configurar allí `ALICE_FILE_ROOT` con una carpeta temporal aislada y validar `/api/identity`, conversaciones, streaming, fuentes y acciones de archivo contra la API en `:8100`.
3. Ejecutar build/tipos y pruebas del frontend, y la suite backend después de integrar; anotar resultados y SHA combinado en `CLAUDE_STATUS.md`.
4. Seguir UI-05/UI-06. `CLAUDE_STATUS.md` indica que la maqueta de Figma se recibió el 2026-09-30, con D-01–D-04 aplicados; D-05 (orbe shader) sigue pendiente de decisión del usuario.
