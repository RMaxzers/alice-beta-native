# Integraciones del área de Conocimiento

Dos integraciones nuevas en Conocimiento: ver planillas con Univer (siempre disponible, sin salida a
red) y un envío opcional a Google NotebookLM (C2, desactivado por defecto).

## Univer: ver planillas

Documentos `csv`/`xlsx` ya listos muestran «Abrir planilla» en el panel de detalle
(`apps/web/src/knowledge/DocDetail.tsx`). Abre un panel a todo el ancho
(`apps/web/src/knowledge/SpreadsheetViewer.tsx`) con una hoja de [Univer](https://univer.ai/) de solo
lectura sobre los datos ya importados — no sube nada, no llama a ningún servicio externo.

- Backend: `GET /api/datasets/{document_id}/rows?limit=500` (`apps/api/routes_knowledge_extra.py`).
  Solo lee el conjunto de datos del documento del usuario que hace la petición (`datasets.table_name`
  viene siempre de la base de datos, nunca de la petición); consulta de solo lectura
  (`file:...?mode=ro`) contra `storage/sqlite/tables.db`, límite duro de 5000 filas. Responde
  `{columns, rows, total, truncated}`.
- Frontend: `@univerjs/presets` y `@univerjs/preset-sheets-core` se cargan con `import()` dinámico
  dentro de `SpreadsheetViewer.tsx`, así que no engordan el bundle principal — solo se pagan cuando
  alguien abre una planilla. La hoja se crea con `createUniver({ darkMode: true, locale: LocaleType.ES_ES, ... })`
  y `fWorkbook.setEditable(false)`: es de solo lectura de verdad (no solo sin barra de herramientas).
  Si hay más filas que las mostradas, se indica «Mostrando N de M filas». Cierra con Esc o el botón
  «Cerrar»; el foco va al botón de cerrar al abrir.

## NotebookLM (opcional, C2, desactivado por defecto)

Usa el CLI no oficial [`notebooklm`](https://pypi.org/project/notebooklm-py/) (paquete
`notebooklm-py`), que reutiliza las cookies de Google del usuario tras `notebooklm login`. **Es un
proyecto no oficial y puede romperse** con cambios de NotebookLM. Alice nunca automatiza el login ni
lee el archivo de cookies (`~/.notebooklm/profiles/<perfil>/storage_state.json`) directamente — eso lo
hace el usuario a mano, fuera de Alice.

### Cómo activarlo

1. Instala el CLI (ya está en este equipo) y ejecútalo tú mismo: `notebooklm login` (abre un navegador).
2. En tu `.env`: `NOTEBOOKLM_ENABLED=true`. Reinicia Alice.
3. En Conocimiento, abre un documento: si el CLI está instalado y con sesión, aparece «Enviar a
   NotebookLM» en el panel de detalle. Si falta algo, se explica ahí mismo (deshabilitado, no
   instalado, sin sesión) en vez de mostrar el botón.

Con `NOTEBOOKLM_ENABLED=false` (valor por defecto) o con «Solo local» activo, todas las rutas de
`/api/integrations/notebooklm/*` responden 403 con el motivo en español; ninguna llama al CLI.

### Qué sale del equipo

- **Enviar un documento como fuente**: el archivo original completo sube a NotebookLM/Google. Se
  revierte borrando la fuente en NotebookLM (Fuentes → eliminar).
- **Preguntar**: el texto de la pregunta se envía a NotebookLM. Queda en el historial de conversación
  del notebook; se borra desde «Historial» en NotebookLM.

Nada de esto pasa sin que el usuario lo autorice explícitamente para ese envío exacto — ver flujo
abajo. Alice no envía nada a NotebookLM por su cuenta.

### El flujo de autorización (igual que el resto de la salida a la nube)

Es el mismo patrón que el resto de Alice para salir a la nube (`services/policies/egress.py`,
`EgressGate`): vista previa → ticket de un solo uso → el usuario aprueba → envío. Cada acción queda en
`actions` (docs/AUTONOMY.md) como `notebooklm.add_source` o `notebooklm.ask`, nivel **C2**: se crea
`awaiting_authorization` en la vista previa, pasa a `running` justo antes de llamar al CLI, y solo llega
a `done` si el CLI devuelve una respuesta válida — nunca de forma optimista. Si el CLI falla o no
confirma, la acción queda `failed` con el error.

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/integrations/notebooklm/status` | Instalado / con sesión / motivo |
| POST | `/api/integrations/notebooklm/preview` | `{document_id, notebook}` → vista previa + ticket |
| POST | `/api/integrations/notebooklm/send` | `{ticket_id}` → envía el documento como fuente |
| POST | `/api/integrations/notebooklm/ask/preview` | `{notebook, question}` → vista previa + ticket |
| POST | `/api/integrations/notebooklm/ask/send` | `{ticket_id}` → hace la pregunta |

El ticket es de un solo uso, caduca a los 5 minutos y está atado a usuario, proveedor, modelo, hash
exacto del payload y coste máximo (0 USD; NotebookLM no tiene coste por token en Alice). Si el
documento cambia entre la vista previa y el envío (otro checksum), el hash ya no coincide y `send`
responde 409 en vez de enviar contenido distinto al que se mostró. Reenviar un ticket ya usado también
da 409.

### Código

- `services/integrations/notebooklm.py`: ejecuta el CLI con `asyncio.create_subprocess_exec` y un
  argv **fijo** (nunca `shell=True`; los datos del usuario son siempre valores, nunca nombres de flag).
  Un notebook dado por título o id siempre se resuelve antes contra `notebooklm list --json`, así que
  solo se pasa a `-n` un id ya confirmado que existe. Timeouts: 15 s para `status`/resolución de
  notebook, 60 s para añadir una fuente, 120 s para preguntar.
- `apps/api/routes_knowledge_extra.py`: las cuatro rutas de arriba, más la ruta de filas de la
  sección Univer. Reutiliza `EgressGate` tal cual (no se reimplementa la política de salida).

### Pruebas

`tests/unit/test_notebooklm.py` (CLI falso vía `asyncio.create_subprocess_exec` parcheado: argv fijo,
timeouts, parseo de estado) y `tests/security/test_knowledge_extra_api.py` (auth, CSRF, aislamiento por
usuario de `/rows`, y el envío rechazado sin ticket aprobado, con ticket ya usado, con el documento
cambiado, deshabilitado y en modo «Solo local»). Ninguna prueba necesita el CLI instalado ni con sesión
iniciada.
