# Inventario del entorno (saneado)

Tomado el 2026-09-22 en modo solo lectura. Nunca se leyeron ni imprimieron valores secretos; solo se registró su presencia.

## Host
| Elemento | Observado |
|---|---|
| SO | Windows 11 Pro 10.0.26200 |
| CPU | Muestra de ingeniería Intel Tiger Lake-H (se identifica como "Genuine Intel CPU 0000 @ 2.60GHz"), chip de portátil en placa de sobremesa (ERYING HM570) |
| RAM | 15,8 GB en total, ~8,6 GB libres en reposo con aplicaciones de usuario abiertas |
| Disco | C: 496 GB libres |
| GPU | NVIDIA GeForce RTX 3070 Laptop GPU, 8192 MiB, nvidia-smi OK, driver 610.47 (INF oem20.inf, 32.0.16.1047, build modificada "Frankenstein" para SUBSYS_000010DE) |
| Estabilidad | 6 reinicios inesperados Kernel-Power 41 en 14 días (08-09, 17-09 x2, 19-09 x3), sin bugcheck registrado para ellos; último BSOD 0xD1 el 03-09 |
| Hipervisor | No presente. VT-d deshabilitado en BIOS |
| WSL | No instalado |
| Docker | No instalado |

## Software
| Elemento | Observado |
|---|---|
| Ollama | 0.34.2, `%LOCALAPPDATA%\Programs\Ollama`, modelos en `~\.ollama\models` (2,3 GB): `qwen3:4b-instruct-2507-q4_K_M`, `asistente-local:v1` (derivado). Sin variables OLLAMA_*. Endpoint 127.0.0.1:11434; no estaba en marcha durante el inventario |
| Open WebUI | Datos en `%LOCALAPPDATA%\IA-Lab\OpenWebUI\data`; lanzador no encontrado; no escuchaba durante el inventario |
| Hermes Agent | v0.21.3 (2026.9.14), instalación git en `%LOCALAPPDATA%\hermes\hermes-agent`; proveedor openrouter + perfil ollama local; incluye un servidor API compatible con OpenAI (`gateway/platforms/api_server*.py`). `.env` contiene OPENROUTER_API_KEY y TAVILY_API_KEY (presentes, valores no mostrados) |
| Tailscale | 1.102.2, nodo `eva01` (100.126.106.61). Serve existente: `https://eva01.tail3f8e85.ts.net/ -> http://127.0.0.1:8080` (solo tailnet). Funnel: ninguno. La tailnet incluye un dispositivo de otro usuario |
| GitHub CLI | sesión iniciada como RMaxzers, scopes repo/read:org/gist |
| Runtimes | Python 3.14.7 (sistema), uv (incluido con Hermes), Node 24.19.0, Git 2.55 |

## Puertos en escucha durante el inventario
135/445/139 (Windows), 3389 RDP en 0.0.0.0 (preexistente, Alice no lo cambió), 443 tailscaled en la IP de la tailnet, 5040/5357/7680 (Windows), 9180 lghub_updater (loopback).

Observación posterior (2026-09-22 23:30): Ollama 0.34.3, arrancado por la app de bandeja de Ollama, escucha en `[::]:11434` (todas las interfaces), no solo en loopback. Ver `docs/SECURITY.md`.

## Variables de entorno (solo presencia)
OPENROUTER/ANTHROPIC/OPENAI/DEEPSEEK/GEMINI/GRAFANA/TAVILY: ninguna definida en ámbito de usuario ni de máquina.
