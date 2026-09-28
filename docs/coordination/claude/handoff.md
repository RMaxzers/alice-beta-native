# Handoff · Claude (UI/Figma) · alice-next-20260928-01

Rama `feat/alice-ui-figma` · base `bc37fd4` · worktree `C:\Users\cuent\alice-ui-claude`. Sin secretos.

## Hecho

- UI-00: worktrees y `BOOTSTRAP.md` (ejecución anterior del mismo día, verificados).
- UI-01: inventario en `docs/design/inventario-ui.md`.
- UI-02: 22 frames (18 escritorio, 4 móvil) en https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5, páginas `00 · Índice` … `04 · Cambios`.
- Demo aislada para captura y QA visual: `apps/web/demo/mock.ts`, `apps/web/vite.demo.config.ts`, script `npm run demo` (puerto 5174). Solo fixtures sintéticos; fuera del build de producción.

## Contrato

`API_CONTRACT.md` v1 de Codex aceptado para la web, con las solicitudes R-01..R-03 registradas en `CLAUDE_STATUS.md`.

## UI-04 · parte funcional (contrato v1, sin cambios visuales de la maqueta)

- `Chat.tsx` detecta v1 con `GET /api/identity` (`api_contract: "1"`). Con v1 envía solo el turno actual, `conversation_id` y un `client_request_id` nuevo por petición (también al autorizar o continuar en local); sin v1 conserva el envío de `history` del backend anterior.
- Evento `conversation`: fija la conversación activa. «Conversaciones» (desplegable del compositor) lista y reabre conversaciones del servidor; los turnos interrumpidos, fallidos o pendientes de autorización muestran una nota.
- Acciones de archivo: el evento `action` con `operation_id` se pinta como tarjeta propia (en ejecución / resultado verificado / error / resultado desconocido) con destino, equipo, bytes y SHA-256. «Acciones» lista `GET /api/file-actions?conversation_id=` con el equipo ejecutor.
- Probado solo contra la demo (`npm run demo`, contrato v1 simulado; `?contract=0` simula el backend anterior). **No probado contra el backend real de Codex** (sin commits integrables).
- Limitación conocida: al reabrir, las fuentes, ruta y tarjetas no se rehidratan (depende de R-03).

## Pendiente

- UI-03: bloqueado hasta que el usuario entregue el enlace de su maqueta.
- UI-04 visual: según la maqueta.
- UI-05/06: tras UI-04 y commits listos de Codex.

## Punto de reanudación

Leer `alice-coordination/CODEX_STATUS.md` y `API_CONTRACT.md`; si hay enlace de maqueta, leer sus nodos con el MCP de Figma y abrir filas en `docs/design/figma-sync.md`.
