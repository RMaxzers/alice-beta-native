# Backup y restauración

Scripts: `scripts\windows\Backup-Alice.ps1` y `scripts\windows\Restore-Alice.ps1`. Vector store: Qdrant **servidor** (se usan snapshots de su API; no hay modo embebido en esta beta).

## Qué se copia

| Parte | Método |
|---|---|
| `storage\sqlite\*.db` (`alice.db`, `tables.db`) | API de backup de `sqlite3` desde el python del venv, seguida de `PRAGMA integrity_check` y recuento de filas por tabla |
| Qdrant | `POST /collections/{c}/snapshots?wait=true` por colección, descarga del `.snapshot` y borrado del snapshot en el servidor |
| `data\raw`, `data\processed`, `data\verified` | copia de ficheros |
| `manifest.json` | formato `alice-backup/1`, fecha UTC, host, versión de Alice, commit Git, modo de consistencia, modo/versión del vector store, puntos por colección, recuentos SQLite, y tamaño + SHA256 de cada archivo |

No se copian `.env` (secretos), `storage\prometheus`, `storage\grafana` ni `logs`. Guarda `.env` aparte y con acceso restringido si necesitas restaurar en otro equipo.

Destino por defecto `backups\alice-<aaaammdd-hhmmss>\` (excluido de Git; ACL solo para el usuario actual y SYSTEM). Se escribe primero en `*.partial` y se renombra al terminar; si algo falla, la carpeta parcial se borra. Retención por defecto: 3 copias (`-Keep`). Un snapshot de Qdrant ocupó ~545 MB con solo 7 puntos, porque incluye segmentos preasignados; ten en cuenta el disco.

## Consistencia

- Por defecto (offline): el script detiene el proceso propio `alice-api` con `Stop-Alice.ps1 -Only alice-api`, lo que pausa toda mutación (ingestión, borrado, hechos, ledger). Al terminar, con o sin error, ejecuta `Start-Alice.ps1`. Si la API está en marcha pero no es un proceso propio, se niega (exit 2).
- `-Online`: no detiene la API. SQLite y Qdrant quedan consistentes cada uno por separado, pero si hay una ingestión en curso el catálogo y los vectores pueden no corresponderse. El manifiesto lo registra en `consistency`. Restore-Alice detecta esa discrepancia.

## Restauración

```powershell
.\scripts\windows\Restore-Alice.ps1 -Backup backups\alice-20260922-233933 -Destination 'D:\restore prueba'
```

1. Valida `manifest.json` y el SHA256 de cada archivo. Cualquier diferencia aborta antes de escribir nada (exit 2).
2. El destino debe no existir o estar vacío. Si el destino es la instalación activa hace falta `-Force` y además la API (8000) y Qdrant (6333) deben estar detenidos; en ese caso los directorios actuales se apartan como `*.pre-restore-<fecha>`, no se borran.
3. Copia SQLite y `data\`.
4. Arranca un `qdrant.exe` temporal (el binario fijado de `infra\bin`) en 127.0.0.1:6343 con almacenamiento en `<destino>\storage\qdrant`, sube cada snapshot (`/snapshots/upload?priority=snapshot`), compara los puntos con el manifiesto y lo detiene (`-KeepQdrant` lo deja en marcha). Nunca toca el Qdrant activo.
5. Verifica: recuentos SQLite = manifiesto; filas de `chunks` = suma de `documents.chunks` (documentos `ready`) = puntos de `alice_chunks`; cada `documents.stored_path` existe en `data\`.

Códigos de salida: 0 restaurado y verificado, 1 verificación fallida, 2 backup inválido o salvaguarda.

## Prueba realizada (2026-09-22 23:39)

Con la demo sintética cargada (4 documentos, 7 fragmentos) y la API en marcha, así que en modo `-Online` (a este agente no se le permitía parar la API):

```text
Backup-Alice.ps1 -Online
  alice.db integrity=ok tablas=9; tables.db integrity=ok tablas=1
  alice_chunks points=7 snapshot=545,0 MB
  Backup completo: backups\alice-20260922-233933 (11 archivos)          exit 0
Restore-Alice.ps1 -Backup backups\alice-20260922-233933 -Destination 'work\restore test 1'   (ruta con espacios)
  11 archivos OK
  alice_chunks puntos restaurados=7 manifiesto=7 OK
  documentos=4 (ready=4); filas chunks=7; suma documents.chunks=7; puntos Qdrant=7; raw ausentes=0
  Restauración verificada                                                exit 0
```

Salvaguardas probadas: destino no vacío → exit 2; destino = instalación activa sin `-Force` → exit 2; con `-Force` pero API/Qdrant activos → exit 2; backup manipulado (un byte cambiado en `tables.db`, snapshot ausente) → dos `checksum FAIL`, exit 2 y el destino no se crea.

PENDIENTE: ejecutar una vez el modo por defecto (offline), que detiene y reanuda la API, en una ventana en la que nadie esté usando Alice.
