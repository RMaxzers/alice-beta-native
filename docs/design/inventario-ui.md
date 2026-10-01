# Inventario de la web y línea base en Figma (UI-01 / UI-02)

Ejecución `alice-next-20260928-01` · base `bc37fd4` (= `main`) · capturado el 2026-09-28.

Archivo Figma de línea base: https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5 (borrador en el plan personal; el plan «ALICE» solo tiene asiento View). **No es la maqueta nueva del usuario ni un diseño aprobado.**

## Cómo se capturó

- Demo aislada, solo desarrollo: `cd apps/web && npm run demo` → `http://127.0.0.1:5174`. Sirve la SPA real con `/api/*` respondido por `apps/web/demo/mock.ts` (fixtures sintéticos de `data/samples`). No arranca backend, no lee `storage/`, no entra en `npm run build`.
- Estados: `GET /__demo/set?mode=normal|empty|error&auth=1|0`. Login demo: cualquier usuario, contraseña `demo`.
- Arnés `http://127.0.0.1:5174/__demo/harness`: carga la app en un iframe de tamaño fijo (viewport exacto aunque la ventana no se pueda redimensionar) y expone `load(w,h,hash,q)`, `click(texto)`, `sendMessage(mensaje)` y `cap(captureId)`. El `captureId` sale de `generate_figma_design` (MCP de Figma) y se sondea con la misma herramienta.
- La app usa `location.hash` para navegar, así que el flujo `#figmacapture=` no sirve; se llama a `window.figma.captureForDesign` dentro del iframe.

## Matriz de pantallas y estados

Tema oscuro en todos (el claro es automático por sistema y no se capturó). Commit `bc37fd4` en todos.

| ID | Ruta | Estado | Viewport | Nodo Figma |
|---|---|---|---|---|
| D01 | `#today` | con datos (vencidas, hoy, próximas, sin fecha, borradores, recomendaciones, acciones) | 1440×900 | [1:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=1-2) |
| D02 | portal | sesión cerrada (login) | 1440×900 | [2:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=2-2) |
| D03 | `#today` | vacío | 1440×900 | [3:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=3-2) |
| D04 | `#today` | error de backend (503) | 1440×900 | [4:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=4-2) |
| D05 | `#home` | mapa en vivo de rutas | 1440×900 | [5:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=5-2) |
| D06 | `#chat` | autorización de salida a la nube (Autorizar / Continuar localmente / Cancelar) | 1440×900 | [6:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=6-2) |
| D07 | `#chat` | respuesta RAG + tarjeta de acción «Hecho» con Deshacer + error de proveedor | 1440×900 | [7:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=7-2) |
| D08 | `#knowledge` | Órbita | 1440×1400 | [8:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=8-2) |
| D09 | `#knowledge` | Órbita + detalle de documento (PDF) | 1440×1400 | [9:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=9-2) |
| D10 | `#knowledge` | Mapa de similitud | 1440×1400 | [10:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=10-2) |
| D11 | `#knowledge` | Lista (incluye en proceso y fallido) | 1440×1400 | [11:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=11-2) |
| D12 | `#knowledge` | planilla CSV abierta (Univer) | 1440×900 | [12:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=12-2) |
| D13 | `#knowledge` | vacío | 1440×900 | [13:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=13-2) |
| D14 | `#observability` | métricas, salud, gráficos | 1440×1400 | [14:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=14-2) |
| D15 | `#models` | alias y rutas | 1440×900 | [15:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=15-2) |
| D16 | `#system` | todo operativo | 1440×1400 | [16:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=16-2) |
| D17 | `#system` | degradado (Ollama no disponible) | 1440×1400 | [17:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=17-2) |
| D18 | `#settings` | ajustes + memoria | 1440×1400 | [18:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=18-2) |
| M01 | `#today` | con datos | 390×844 | [19:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=19-2) |
| M02 | `#chat` | RAG + acción | 390×844 | [20:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=20-2) |
| M03 | `#knowledge` | Lista | 390×844 | [21:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=21-2) |
| M04 | portal | sesión cerrada | 390×844 | [22:2](https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5?node-id=22-2) |

## Sin capturar (a propósito o pendiente)

- Voz (grabando / transcribiendo / reproduciendo): requiere micrófono y audio reales; el botón aparece en reposo en D06/D07.
- Autorización NotebookLM en el detalle: integración apagada por defecto; se ve su estado deshabilitado en D09.
- Subida de archivos en curso y confirmación de eliminación: estados transitorios; no aportan layout nuevo.
- Tema claro y `prefers-reduced-motion`: se revisan en UI-05 en navegador, no como frames.

## Limitaciones de la captura

- Rasterizados (una imagen, sin capas): canvas del portal (D02, M04), mapa de similitud (D10) y la rejilla Univer (D12). Los 18 frames restantes conservan texto editable (26–176 capas de texto por frame).
- Fuentes reales conservadas (Chakra Petch, Geist, Geist Mono) solo si están disponibles para la cuenta de Figma.
- El `<input type="file">` nativo pierde su texto («Elegir archivos») y queda como caja vacía.
- Cada frame es el viewport, no la página completa con scroll: en D01/D06 quedan contenidos por debajo del pliegue.
- Animaciones (rayos del portal, estela del chat, borde que late, estados del gato) no se trasladan.
- Una captura no traslada lógica, navegación ni backend, y no se sincroniza sola.

## Hallazgos para la maqueta

- Móvil: la barra inferior tiene 8 pestañas y se desborda con scroll horizontal (Modelos, Sistema y Ajustes quedan ocultos a 390 px).
- Conocimiento: a 1440×900 la órbita queda casi bajo el pliegue porque la zona de subida ocupa la parte alta.
- Chat: no hay lista de conversaciones; al recargar se pierde la conversación (el contrato v1 de Codex lo resuelve en el backend).
- No existe una vista de acciones: las acciones solo aparecen como tarjetas dentro del chat y en «Acciones recientes» de Hoy.
