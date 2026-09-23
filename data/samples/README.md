# Dataset sintético de demostración

Todos los archivos de esta carpeta son **ficticios**, creados para la demo de Alice Beta 0.1 (guion en `docs/DEMO.md`).
No contienen datos personales ni de ninguna organización real. «Laboratorio Demo» es un nombre inventado.

| Archivo | Uso en la demo | Respuesta esperada (para comprobar) |
|---|---|---|
| `manual-red-laboratorio-demo.pdf` | RAG sobre PDF (paso 4), 2 páginas | La página 2 indica que la VLAN de invitados es la 30 y que el arrendamiento DHCP de invitados dura 4 horas |
| `guia-dhcp-laboratorio-demo.md` | RAG sobre Markdown (paso 4) | Sección «Reserva de direcciones»: el rango reservado es 192.168.10.1–192.168.10.49 |
| `inventario-laboratorio-demo.csv` | SQL restringido (paso 5) | 12 activos; **4** con `estado_soporte = fuera_de_soporte` |
| `ingestion-laboratorio-demo.log` | Análisis de logs (paso 9) | 3 ERROR (2 con la plantilla «timeout al generar embeddings…», 1 «PDF cifrado…»), 2 WARN; un token de ejemplo que debe aparecer como `<REDACTED>` |
| `hecho-verificado-demo.json` | Hecho verificado (`POST /api/facts`) | `servidor-dhcp-demo.ip` = 192.168.10.2 |

`scripts/windows/Demo-Alice.ps1` verifica estos archivos (checksums en `SHA256SUMS`) y, con `-Load`, los carga en la instancia local.
