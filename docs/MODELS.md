# Modelos

Medido el 2026-09-22 con Ollama 0.34.3 (`/api/tags`, `ollama show`, `ollama ps`) en la RTX 3070 Laptop (8 GB VRAM). Alias en `config/models/aliases.yaml`.

## Locales

| Alias | Modelo | Digest (`/api/tags`) | Parámetros / cuantización | Contexto nativo / usado | Licencia (`ollama show`) | VRAM cargado (`ollama ps`) |
|---|---|---|---|---|---|---|
| local-general, local-code, local-classifier | `qwen3:4b-instruct-2507-q4_K_M` | `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0` | 4.0B, Q4_K_M, GGUF, 2,50 GB en disco | 262144 / 4096 (clasificador 2048) | Apache 2.0 | 3,2 GB, 100 % GPU, contexto 4096 |
| local-embedding | `bge-m3:latest` | `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab` | 566.70M, F16, 1,16 GB en disco, 1024 dimensiones | 8192 | MIT | 664 MB, 100 % GPU |
| (no usado por Alice) | `asistente-local:v1` | `799c5fecd7e6e05d5a8a9987f26aa83f6a50759ce8ad2687c7bebc548dbc312f` | derivado de qwen3:4b-instruct-2507-q4_K_M | | | |

Motivo de selección: D3 (qwen3 ya instalado, tamaño 3-4B, cabe en VRAM junto a bge-m3) y D4 (bge-m3 multilingüe con buen español). Con ambos cargados, `nvidia-smi` marcó 5,8-6,2 GB de VRAM usada en total (incluye el escritorio de Windows y otras aplicaciones).

## Latencia medida

Generación directa a Ollama, prompt «Explica DHCP en una frase.» (15 tokens), `num_ctx=4096`, `num_predict=64`, `temperature=0`:

| Ejecución | total | carga | prompt | generación | tokens salida | velocidad |
|---|---|---|---|---|---|---|
| caliente 1 | 0,765 s | 0,003 s | 0,189 s | 0,546 s | 39 | 71,4 tok/s |
| caliente 2 | 0,472 s | 0,003 s | 0,010 s | 0,442 s | 39 | 88,2 tok/s |
| fría (ningún modelo cargado, `ollama ps` vacío) | 6,355 s | 5,823 s | 0,106 s | 0,416 s | 39 | 93,7 tok/s |

Extremo a extremo por Alice (`Demo-Alice.ps1 -Smoke`, «Explícame DHCP en pocas palabras», ruta LOCAL_SIMPLE decidida por el clasificador): 12,14 s, 71 tokens de salida, espera en cola 0 s. Ese total incluye routing (aquí por clasificador, que también usa qwen3), cola y generación; el panel «p95 por etapa» del dashboard muestra el reparto.

La carga en frío (~5,8 s) domina la primera petición tras expirar el keep-alive; después la generación ronda 70-95 tok/s.

## Cloud (OpenRouter)

| Alias | Modelo | Contexto | Precio catálogo (USD/token entrada, salida) |
|---|---|---|---|
| cloud-cheap, financial-research | `deepseek/deepseek-v4.1-flash` | 1048576 | 0.0000001, 0.0000005 |
| cloud-powerful | `anthropic/claude-sonnet-5` | 1000000 | 0.000002, 0.00001 |

Datos del catálogo público `https://openrouter.ai/api/v1/models` consultado el 2026-09-22 23:47 (sin clave). La API de Alice lee precios en vivo. PENDIENTE: una llamada real con la clave de Alice (Status muestra `CONFIGURED_NOT_TESTED`).
