# Guion de demostración (10-15 min)

Datos: dataset sintético de demostración en `data\samples` (ver su README). Preparación en el PC:

```powershell
.\scripts\windows\Start-Alice.ps1
.\scripts\windows\Demo-Alice.ps1 -Load -Smoke   # verifica checksums, carga los 4 documentos y el hecho, lanza una consulta local
```

Resultado verificado el 2026-09-22: 4 documentos `ready` (PDF 2 fragmentos, Markdown 5 fragmentos, CSV → tabla de 12 filas, log → 10 eventos), hecho `servidor-dhcp-demo.ip` registrado, consulta de humo por LOCAL_SIMPLE con `qwen3:4b-instruct-2507-q4_K_M`. Los pasos marcados PENDIENTE no se han ensayado de punta a punta.

| # | Acción | Qué debe verse |
|---|---|---|
| 1 | Abrir Alice desde el laptop (`https://eva01.tail3f8e85.ts.net:8443`, PENDIENTE, ver REMOTE-DEMO) y ver el estado del sistema | Estado real de cada componente |
| 2 | «Explícame DHCP en pocas palabras» | Ruta `LOCAL_SIMPLE`, modelo real `qwen3:4b-instruct-2507-q4_K_M` (ensayado con Demo-Alice -Smoke) |
| 3 | «Genera una función que valide estas direcciones IP» | Ruta `LOCAL_CODE`, código sin ejecutar |
| 4 | «¿Qué VLAN usa la red de invitados y cuánto dura su arrendamiento DHCP?» y «¿Qué rango está reservado para infraestructura?» | RAG con cita: PDF página 2 (VLAN 30, 4 horas); Markdown sección «Reserva de direcciones» (192.168.10.1-192.168.10.49) |
| 5 | «¿Cuántos activos del inventario están fuera de soporte según la columna estado_soporte?» | SQL visible; respuesta 4 (A-001, A-004, A-007, A-009) |
| 6 | «¿Qué componente de Alice usa más memoria ahora?» | Datos actuales con unidades (procesos de Windows vía Prometheus). Docker deshabilitado, así que no hay pregunta de contenedores |
| 7 | Abrir ALICE / OVERVIEW (Viewer por la tailnet, PENDIENTE) y lanzar una consulta local larga | CPU/RAM del host, GPU/VRAM y latencia moviéndose. Si el acceso Viewer no está listo, usar la vista de métricas de Alice y decir que el dashboard remoto está pendiente |
| 8 | «¿Qué cambió durante mi última consulta?» | Correlación temporal, sin atribuir causalidad |
| 9 | «Dame los últimos errores de la ingestión» (sobre el log de demo) | 3 ERROR: 2 «timeout al generar embeddings…», 1 «PDF cifrado no soportado»; el token del WARN aparece como `<REDACTED>` |
| 10 | Marcar como `PUBLIC` una pregunta sobre un tema actual o un dato financiero | Fuentes, fechas, proveedor y coste; sin historial privado (requiere prueba real de OpenRouter/Tavily, PENDIENTE) |
| 11 | Pedir en cloud algo sobre el log de demo (documento `PRIVATE`) | Aviso y bloqueo hasta autorizar; opción de seguir en local |
| 12 | «¿Cuántas consultas fueron locales y cuánto costó el cloud hoy?» | Ledger + métricas; «sin datos» de coste si no hubo llamadas cloud, nunca una cifra inventada |

## Plan alternativo sin Internet

En el PC siguen funcionando chat local, RAG, SQL, logs y observabilidad (pasos 2-9 y 12); los pasos 10-11 muestran que el cloud no está disponible. Si el laptop pierde la conexión con la tailnet, la demo continúa en el PC local (`http://127.0.0.1:8000`, Grafana `http://127.0.0.1:3000/d/alice-overview`). Como respaldo, guardar antes de la demo capturas rotuladas con fecha del dashboard y del último `work\test-*\REPORT.md`.
