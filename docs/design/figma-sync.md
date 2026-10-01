# Registro diseño ↔ código

Cada cambio visual que venga de la maqueta del usuario se registra aquí y se refleja en la página `04 · Cambios` del archivo Figma de seguimiento. No se sobrescribe la maqueta del usuario.

- Línea base (actual): https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5 · página `01 · Actual` · commit `bc37fd4`. Detalle en `inventario-ui.md`.
- Maqueta objetivo (entregada 2026-09-30), cuatro referencias:
  - **Dirección principal** · Make «Página inmersiva de IA» `2rXOBX0dMcfcLAtM4ysNEf`: paleta, vidrio, fondo neural, tipografía.
  - Make «Interactive Eye Following Card» `qoWw8mLenLXBP7FS4hrBFC` (Community): ojos que siguen al cursor.
  - Make «Shader Reminder» `5A40MPUJ9ju1R2b981WqTo` (Community): orbe shader + recordatorios. Sin aplicar todavía.
  - Diseño «MCP Apps for Claude» `39VOSgBnu8v8km6XkNLjhg`, nodo `467:20292` (Community): tabla de color superficie/acento claro-oscuro. Usada como referencia de estructura; los tokens ya siguen ese esquema.

Estados: `pendiente`, `en_curso`, `bloqueada`, `lista_para_integrar`, `validada`.

| ID | Nodo de origen | Componente | Motivo | Commit | Comprobación | Estado |
|---|---|---|---|---|---|---|
| D-01 | Make `2rXOBX0d…` `src/index.css` | `theme.css` | Paleta Nebulosa: fondo `#05030f`, cian `#00f5d4`, violeta (texto `#b57cf0`; el `#9d4edd` del Make da 4,2:1 y queda solo decorativo), superficies de vidrio, Outfit + JetBrains Mono autoalojadas | este | Contraste WCAG calculado (anotado en `theme.css`); build OK | lista_para_integrar |
| D-02 | Make `2rXOBX0d…` `NeuralGalaxyBackground` | `Galaxy.tsx`, `main.tsx`, `styles.css` | Fondo de partículas tras el shell; máx. 110 nodos, pausa con pestaña oculta, estático con reduced-motion | este | Demo :5174 Chat y Hoy, consola sin errores | lista_para_integrar |
| D-03 | Make `2rXOBX0d…` `.glass-panel` | `styles.css` `.card` | Tarjetas con blur 12px y halo violeta interior | este | Demo :5174 Hoy | lista_para_integrar |
| D-04 | Make `qoWw8mLe…` `Eye.tsx` | `Logo.tsx`, `logo.css` | La mirada del gato sigue al puntero (≤2,2 u.), apagada con reduced-motion; el gato conserva su identidad | este | `transform` verificado en navegador | lista_para_integrar |
| — | Make `2rXOBX0d…` | — | Descartado: métricas inventadas en inglés, scanline, mascota orbe «Nexus» (Alice es el gato) | — | — | — |
| D-05 | Make `5A40MPUJ…` | por decidir (voz / Hoy) | Orbe shader reactivo a recordatorios | — | — | pendiente |
