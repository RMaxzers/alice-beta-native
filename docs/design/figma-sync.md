# Registro diseño ↔ código

Cada cambio visual que venga de la maqueta del usuario se registra aquí y se refleja en la página `04 · Cambios` del archivo Figma de seguimiento. No se sobrescribe la maqueta del usuario.

- Línea base (actual): https://www.figma.com/design/viXyIiRHGmSCMjfsRjPAF5 · página `01 · Actual` · commit `bc37fd4`. Detalle en `inventario-ui.md`.
- Maqueta objetivo (entregada 2026-09-30), cuatro referencias:
  - **Dirección principal** · Make «Página inmersiva de IA» `2rXOBX0dMcfcLAtM4ysNEf`: paleta, vidrio, fondo neural, tipografía.
  - Make «Interactive Eye Following Card» `qoWw8mLenLXBP7FS4hrBFC` (Community): ojos que siguen al cursor.
  - Make «Shader Reminder» `5A40MPUJ9ju1R2b981WqTo` (Community): orbe shader + recordatorios. Sin aplicar todavía.
  - Diseño «MCP Apps for Claude» `39VOSgBnu8v8km6XkNLjhg`, nodo `467:20292` (Community): tabla de color superficie/acento claro-oscuro. Usada como referencia de estructura; los tokens ya siguen ese esquema.

## Base editable «Nebulosa» (UI-05, 2026-09-30)

Archivo: https://www.figma.com/design/fTT01uMvbNTLFeRttHXx4i («Alice · Nebulosa (base editable)»). Creado en el equipo personal porque el asiento en el equipo ALICE es View; destino previsto: carpeta https://www.figma.com/files/team/1686210817737328529/folder/663390262 (moverlo a mano).

- Página `01 · Nebulosa (capturas de la app)`: N01 Hoy `3:2`, N02 Chat vacío `4:2`, N03 Chat con fuentes `5:2`, N04 Portal `6:2`, N05 Inicio `8:2`, N06 Conocimiento `9:2`, N07 Observabilidad `10:2`, N08 Sistema `11:2`, N09 Ajustes `12:2`, M01 Hoy móvil `7:2`, M02 Chat móvil `13:2`.
- Página `02 · Tus bocetos`: vacía, para los bocetos del usuario. Los cambios que salgan de ahí se registran abajo como D-07…
- Método: demo `:5174` + arnés `/__demo/harness`; antes de `cap()` se congelan los orbes WebGL (`canvas.toDataURL()` → `<img>`), porque la captura ignora WebGL. Fuentes «Outfit Variable»/«JetBrains Mono Variable» sustituidas por Outfit/JetBrains Mono en Figma.
- Limitaciones conocidas de la captura: chips `<details>` del compositor (Adjuntos, Conversaciones) sin texto; líneas de los gráficos de Observabilidad ausentes. No son defectos de la app.

Estados: `pendiente`, `en_curso`, `bloqueada`, `lista_para_integrar`, `validada`.

| ID | Nodo de origen | Componente | Motivo | Commit | Comprobación | Estado |
|---|---|---|---|---|---|---|
| D-01 | Make `2rXOBX0d…` `src/index.css` | `theme.css` | Paleta Nebulosa: fondo `#05030f`, cian `#00f5d4`, violeta (texto `#b57cf0`; el `#9d4edd` del Make da 4,2:1 y queda solo decorativo), superficies de vidrio, Outfit + JetBrains Mono autoalojadas | este | Contraste WCAG calculado (anotado en `theme.css`); build OK | lista_para_integrar |
| D-02 | Make `2rXOBX0d…` `NeuralGalaxyBackground` | `Galaxy.tsx`, `main.tsx`, `styles.css` | Fondo de partículas tras el shell; máx. 110 nodos, pausa con pestaña oculta, estático con reduced-motion | este | Demo :5174 Chat y Hoy, consola sin errores | lista_para_integrar |
| D-03 | Make `2rXOBX0d…` `.glass-panel` | `styles.css` `.card` | Tarjetas con blur 12px y halo violeta interior | este | Demo :5174 Hoy | lista_para_integrar |
| D-04 | Make `qoWw8mLe…` `Eye.tsx` | `Logo.tsx`, `logo.css` | La mirada del gato sigue al puntero (≤2,2 u.), apagada con reduced-motion; el gato conserva su identidad | este | `transform` verificado en navegador | lista_para_integrar |
| — | Make `2rXOBX0d…` | — | Descartado: métricas inventadas en inglés, scanline, mascota orbe «Nexus» (Alice es el gato) | — | — | — |
| D-05 | Make `5A40MPUJ…` `shaders.ts` «Flowing Waves» | `Orb.tsx`, `Chat.tsx`, `voice.ts`, `styles.css` | Orbe de voz: sustituye al logo en el chat vacío (clic = hablar) y flota sobre el compositor mientras se graba, transcribe o Alice habla; reacciona al volumen real (AnalyserNode del micrófono o del TTS). Cian al oír/hablar, violeta al pensar. Transiciones suaves: tinte/energía con suavizado exponencial y fase integrada | este | Demo :5174: idle → grabación (micrófono simulado) → transcripción → idle; dock entra/sale con fundido; consola sin errores | lista_para_integrar |
| D-06 | Make `5A40MPUJ…` | `Today.tsx` `ReminderOrb` | Orbe de recordatorios en Hoy: cobre con vencidas, cian intenso si algo vence en la próxima hora, cian suave con tareas de hoy, violeta si el día está despejado; contador al centro, `role=status` | este | Demo :5174 Hoy («1 tarea vencida», cobre) | lista_para_integrar |
| — | Make `5A40MPUJ…` | — | Descartado: shader «Ether» (licencia CC BY-NC-SA), selector de shaders, toasts y entrada de recordatorios del Make (Hoy ya tiene creación de tareas) | — | — | — |
