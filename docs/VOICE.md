# Voz

Habla para escribir en el chat (STT) y escucha las respuestas de Alice (TTS). Todo ocurre en este equipo:
nada de audio ni de texto sale a internet por esta función.

## Cómo funciona

```
navegador ──MediaRecorder──▶ POST /api/voice/stt ──▶ services/voice/stt.py ──▶ faster-whisper (CPU, local)
navegador ◀──audio/wav────── POST /api/voice/tts ──▶ services/voice/tts.py ──▶ sidecar pocket-tts (127.0.0.1:8010)
```

- **STT (voz → texto):** `services/voice/stt.py` carga un modelo `faster-whisper` una sola vez (perezoso,
  en memoria durante toda la vida del proceso) y transcribe en un hilo aparte (`asyncio.to_thread`) para no
  bloquear el resto de la API. Decodifica el audio con PyAV (incluido en el paquete), así que acepta
  `webm`/`ogg`/`wav` tal cual los graba `MediaRecorder` en el navegador, sin conversión previa. Intenta
  primero en español (`language="es"`, el idioma de la UI); si esa pasada no produce texto, reintenta con
  detección automática de idioma.
- **TTS (texto → voz):** `services/voice/tts.py` reenvía la petición al sidecar `pocket-tts` (Kyutai, voz en
  español) que corre en `http://127.0.0.1:8010` — el mismo patrón de sidecar loopback-only que Qdrant u
  Ollama. Devuelve el WAV tal cual lo entrega el sidecar (`content-type: audio/wav`).
- **Ruta HTTP:** `apps/api/routes_voice.py` expone `/api/voice/status`, `/api/voice/stt` y `/api/voice/tts`,
  todas detrás de sesión (`Depends(require_user)`) y con el mismo CSRF de doble envío que el resto de rutas
  que cambian estado. Respetan `settings.voice_enabled` (si está apagado, responden 503).

## Puertos y modelos

| Pieza | Dónde | Configuración |
|---|---|---|
| Sidecar TTS (pocket-tts) | `127.0.0.1:8010` | `tts_url` en `apps/api/config.py` |
| Modelo STT (faster-whisper) | en memoria del proceso de la API | `stt_model` (por defecto `small`), `stt_device` (por defecto `cpu`, int8) |

El modelo de STT se descarga la primera vez que se usa (caché de Hugging Face) y luego queda en disco; no
hace falta conexión a internet en usos posteriores.

## Límites (aplicados en el servidor)

- `/api/voice/stt`: audio ≤ 10 MB y ≤ 60 s (la duración la reporta faster-whisper tras transcribir).
- `/api/voice/tts`: texto ≤ 2000 caracteres.
- Ambas rutas exigen sesión iniciada y token CSRF en el POST, igual que `/api/documents` o `/api/chat`.

## Interfaz

- **Micrófono en el compositor** (`apps/web/src/Chat.tsx`, estilos en `apps/web/src/voice.css`): un botón
  circular graba con `MediaRecorder`; al soltar, transcribe y **inserta** el texto en el cuadro de mensaje
  (no lo envía solo). Requiere un contexto seguro (`https` o `http://127.0.0.1`) porque `getUserMedia` así
  lo exige en el navegador; si no está disponible, o si el permiso se deniega, o si el servicio de voz está
  caído, se muestra un mensaje en español explicando qué pasó. Respeta `prefers-reduced-motion` (sin pulso
  animado) y expone `aria-pressed` para lectores de pantalla.
- **Botón «Escuchar»** en cada respuesta terminada de Alice: pide el audio a `/api/voice/tts` (quitando
  bloques de código y marcado antes de enviar el texto), lo reproduce y permite detenerlo; solo un audio
  suena a la vez en toda la conversación.

## Privacidad

Ambos servicios son locales (`127.0.0.1`); esta función no está sujeta a las reglas de egress/autorización
del chat porque no hay ningún envío externo que autorizar.
