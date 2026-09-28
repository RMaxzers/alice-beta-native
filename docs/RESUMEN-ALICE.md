# Alice: resumen del estado actual

Actualizado: 28 de septiembre de 2026. Rama `design/tunel-de-luz`. Solo figura lo que está construido y probado; lo pendiente está al final.

Alice es un asistente personal que corre en tu PC con Windows 11. Responde con modelos locales y con tus documentos, organiza tus tareas y solo sale a internet cuando tú lo autorizas, consulta por consulta.

---

## 1. Qué puede hacer hoy

| Área | Qué hace | Dónde |
|---|---|---|
| Chat | Respuestas en streaming con modelo local (qwen3:4b). Un router decide la ruta: local, documentos, código, datos, logs, observabilidad o nube. Muestra ruta, modelo, latencia, coste y fuentes | Pestaña Chat |
| Conocimiento (RAG) | Sube PDF, Markdown, texto, logs, CSV y XLSX; responde con citas a tus documentos | Conocimiento |
| Datos | Consultas SQL de solo lectura sobre tus planillas | Chat (ruta STRUCTURED_QUERY) |
| Tareas | Crear, editar, completar, reordenar y deshacer tareas desde el chat o con clic, con registro de auditoría | Hoy |
| Autonomía graduada | C0 leer · C1 cambios locales reversibles · C2 efecto externo con autorización · C3 revisión. Lo decide el servidor, no el modelo | `docs/AUTONOMY.md` |
| Búsqueda web | Tavily + OpenRouter, siempre con tarjeta de autorización ("Autorizar una vez") | Chat, privacidad PUBLIC |
| Memoria | Recuerda lo que le cuentas (hindsight, local). Solo se usa en rutas locales y nunca sale a la nube | Chat · Ajustes → Memoria |
| Voz | Dictado por micrófono (Whisper) y lectura de respuestas en español (pocket-tts). Todo local | Botón de micrófono · "Escuchar" |
| Planillas | Visor de solo lectura de CSV/XLSX con Univer (hasta 5.000 filas) | Conocimiento → Abrir planilla |
| NotebookLM | Enviar un documento o preguntar a un cuaderno. Apagado por defecto y siempre con autorización C2 | Conocimiento → Enviar a NotebookLM |
| Observabilidad | Prometheus + Grafana (dashboard ALICE / OVERVIEW), GPU, procesos y latencias | Observabilidad · Grafana :3000 |
| Acceso remoto | Solo por Tailscale: `https://eva01.tail3f8e85.ts.net:8443/` | Laptop dentro de la tailnet |

## 2. Diseño: "Túnel de luz"

**Idea.** Alice es un gato con casco visto por una lente ojo de pez, que viaja por un túnel de luz (referencia: *Chungking Express*). El negro es la carretera, y **el color aparece solo donde se mueve información**.

**Referencias elegidas.** Póster negro con anillos orbitales dorados y cian y paneles tipo HUD; estallido de rayos cobre; el gato con casco en ojo de pez con neón teal; PromptNest (monocromo, anillo de luz y botones en píldora).

### Paleta (tokens en `apps/web/src/theme.css`)

| Token | Oscuro | Uso |
|---|---|---|
| `--bg` | `#000000` | Fondo |
| `--text` / `--ivory` | `#F2EFE6` | Texto y botones principales en píldora |
| `--accent` / `--route-local` | `#2FE0C4` | Teal neón: Alice y lo local |
| `--accent-2` | `#E8B04A` | Oro: órbitas y "decidiendo ruta" |
| `--route-cloud` | `#E0703A` | Cobre: la nube |
| `--route-knowledge` | `#4787DE` | Azul: tus documentos |
| `--route-obs` | `#C4B5FD` | Lavanda: telemetría |

Todos los colores de texto cumplen WCAG AA sobre las superficies (el contraste está calculado en los comentarios de `theme.css`). Hay modo claro automático según el sistema operativo.

**Tipografía.** Chakra Petch para títulos (tiene aire de HUD y de visera de casco), Geist para el texto y Geist Mono solo para telemetría. Todas las fuentes son locales, sin CDN.

### Elementos

- **Ícono.** Gato con casco en lente ojo de pez, dibujado como vector original (`Logo.tsx` + `logo.css`). El aro, las líneas de velocidad, los remaches y el brillo de los ojos toman el color de la ruta. Tiene 7 estados: en espera (parpadea), decidiendo ruta (líneas de velocidad), local, conocimiento, nube, telemetría y error (sacude la cabeza).
- **Login "portal".** Una lente circular con cientos de rayos de luz, anillos dorados en órbita y estrellas, con el gato al centro (`landing/Portal.tsx`, canvas limitado a 30 fps). Al entrar, los rayos aceleran; si hay un error, el aro parpadea en rojo.
- **Chat dinámico.**
  - Al enviar, sale una estela de luz desde el compositor.
  - Una línea bajo la barra superior se ilumina en oro mientras decide la ruta y luego toma el color de la ruta.
  - La respuesta en curso tiene un borde que late.
  - Los detalles se muestran como un HUD compacto.
- **Conocimiento.**
  - Vista **Órbita**: los documentos giran alrededor del gato en anillos por tipo.
  - Vista **Mapa**: un grafo de documentos conectados por similitud semántica, con "Trazar camino".
  - Vista **Lista**.
  - Zona para arrastrar archivos.
- **Accesibilidad.** Con `prefers-reduced-motion` todo queda estático. El foco de teclado es visible. El mapa tiene una alternativa en lista para lectores de pantalla.

### Figma

Archivo: https://www.figma.com/design/USNTu1Mh15ZfSXgiYmLwJ9 (equipo de estudiante).

- **Fundamentos:** variables de color (Oscuro/Claro), tamaños, estilos de texto, el componente "Ícono Alice (gato)" con 7 estados, botones, badges, navegación y fila de tarea.
- **Pantallas:** Chat, Hoy y Hoy en modo claro.
- **Concepto · Orbe vivo:** exploración anterior, con las tarjetas de acción (Hecho / Esperando autorización / Resultado web / Falló) que sirven de base para las acciones externas.

## 3. Arquitectura

Todo corre de forma nativa en Windows, escuchando solo en 127.0.0.1. No usa WSL, Hyper-V ni Docker.

| Componente | Puerto | Notas |
|---|---|---|
| Alice API + UI (FastAPI + React/Vite) | 8000 | Detrás de Tailscale Serve :8443 |
| Métricas de Alice | 9101 | |
| Ollama (qwen3:4b, bge-m3) | 11434 | Reutilizado; Gemma 4 E4B instalado pero sin uso |
| Qdrant | 6333 | Vectores de tus documentos |
| hindsight (memoria) | 8888 | Sidecar con su propio entorno; Postgres embebido en :5432 (datos en `~\.pg0`) |
| pocket-tts (voz en español) | 8010 | Sidecar en CPU |
| Prometheus / Grafana / windows_exporter | 9090 / 3000 / 9182 | |

- `scripts\windows\Start-Alice.ps1` levanta todo, incluidos los sidecars; `Stop-Alice.ps1` lo detiene y `Status-Alice.ps1` muestra el estado.
- Los sidecars pesados viven aislados en `storage\sidecars\` para no romper el entorno de Alice.
- Para apagar la memoria o la voz: `MEMORY_ENABLED=false` / `VOICE_ENABLED=false` en `.env`.

## 4. Privacidad y seguridad

- **Nada sale del equipo sin autorización.** Cada salida a la nube pasa por `EgressGate`, con un ticket de un solo uso ligado a usuario, destino, hash del contenido, coste y vencimiento.
- El modo **"Solo local"** bloquea toda salida desde el backend.
- Los documentos, logs, respuestas web y **recuerdos** son **datos no confiables**: nunca dan permisos ni cambian la ruta.
- La memoria no se inyecta en rutas de nube, cada usuario tiene su propio banco, y guardar recuerdos nunca retrasa la respuesta.
- NotebookLM usa una API **no oficial**: envía el archivo completo a Google, así que queda apagado por defecto y es C2 con vista previa exacta.
- Hay sesión con cookie segura, CSRF y límites de subida en el servidor. Los endpoints nuevos exigen login.

## 5. Pruebas

- `pytest`: **424 pruebas en verde**. Cubren privacidad y egress, SQL, ingestión, SSRF, seguridad de la API, tareas y autonomía, mapa de conocimiento, memoria, voz, NotebookLM y el visor de planillas.
- Router: 52/52 casos, con qwen3:4b y también con Gemma 4 E4B (este último con `think: false`).
- Frontend: `tsc --noEmit` y `vite build` sin errores. Univer se carga aparte, bajo demanda.

## 6. Decisiones de esta etapa

- **D15–D17:** autonomía C0–C3 decidida por el servidor; tareas interpretadas con reglas; C2 sin ejecutor hasta tener un caso concreto (`docs/DECISIONS.md`).
- **D18:** memoria local con hindsight como sidecar, solo en rutas locales; los recuerdos son datos no confiables.
- **Modelo:** se mantiene qwen3:4b. Gemma 4 E4B empató en el router, pero fue más lento y más verboso.
- **Descartados por ahora:** paperclip y openrig (se superponen con Alice, y openrig no funciona en Windows), mimalloc-pprof, disktree, VoiceStudio (demasiado pesado; se usa pocket-tts) y better-auth (es TypeScript y Alice usa Python).

## 7. Pendiente

1. Primera búsqueda web real (Tavily/OpenRouter), a cargo del usuario.
2. Corregir el bug de sesión: la conexión SQLite compartida entre hilos causa `InterfaceError` con peticiones simultáneas.
3. Incluir la memoria (`~\.pg0`) en Backup-Alice.
4. Primera acción externa C2 real. Propuesta: crear eventos en Google Calendar usando la tarjeta "Evento propuesto".
5. RAM: con todo cargado quedan ~1,8 GB libres de 16. Vigilar la estabilidad (hay historial de reinicios Kernel-Power 41).
6. Olvidar recuerdos "consolidados" de hindsight (hoy falla; hay que borrar sus fuentes).
7. pocket-tts de los resúmenes de voz de Claude choca con Alice en el puerto 8000; hay que moverlo.
8. Skills de diseño para Claude Code: impeccable falló al instalar (404 del proyecto); last30days está pendiente.
9. Probar desde fuera de la red de la casa y medir una sesión sostenida de 30 minutos.

## 8. Documentos relacionados

`README.md` · `docs/ARCHITECTURE.md` · `docs/SECURITY.md` · `docs/AUTONOMY.md` · `docs/INTEGRATIONS.md` · `docs/VOICE.md` · `docs/MODELS.md` · `docs/DECISIONS.md` · `docs/ROADMAP.md` · `docs/STATUS.md` · `docs/REMOTE-DEMO.md`
