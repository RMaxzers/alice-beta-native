# Backup y restauración

Scripts: `scripts\windows\Backup-Alice.ps1` y `scripts\windows\Restore-Alice.ps1`. Vector store: Qdrant **servidor** (se usan snapshots de su API; no hay modo embebido en esta beta).

## Qué se copia

| Parte | Método |
|---|---|
| `storage\sqlite\*.db` (`alice.db`, `tables.db`) | API de backup de `sqlite3` desde el python del venv, seguida de `PRAGMA integrity_check` y recuento de filas por tabla |
| Qdrant | `POST /collections/{c}/snapshots?wait=true` por colección, descarga del `.snapshot` y borrado del snapshot en el servidor |
| `data\raw`, `data\processed`, `data\verified` | copia de ficheros |
| `memory/hindsight.dump` | `pg_dump` de Hindsight y PostgreSQL `pg0`, con un snapshot exportado compartido con los recuentos de tablas y estados de trabajo |
| `manifest.json` | formato `alice-backup/2`, fecha UTC, host, versión de Alice, commit Git, modo de consistencia, modo/versión del vector store, puntos por colección, recuentos SQLite y Hindsight, estados de trabajos pendientes/en curso, y tamaño + SHA256 de cada archivo |

No se copian `.env` (secretos), `storage\prometheus`, `storage\grafana` ni `logs`. Guarda `.env` aparte y con acceso restringido si necesitas restaurar en otro equipo. El destino y los archivos del backup deben pertenecer a la ruta elegida; la validación aborta ante traversal, enlaces o checksum incorrecto.

Destino por defecto `backups\alice-<aaaammdd-hhmmss>\` (excluido de Git; ACL solo para el usuario actual y SYSTEM). Se escribe primero en `*.partial` y se renombra al terminar; si algo falla, la carpeta parcial se borra. Retención por defecto: 3 copias (`-Keep`). Un snapshot de Qdrant ocupó ~545 MB con solo 7 puntos, porque incluye segmentos preasignados; ten en cuenta el disco.

## Consistencia

- Por defecto: el script detiene el proceso propio `alice-api` para pausar mutaciones SQLite, exporta el snapshot PostgreSQL de Hindsight mientras su servidor sigue activo y solicita snapshots de Qdrant. Cada motor queda consistente dentro de su propio snapshot. **No hay snapshot atómico entre SQLite, PostgreSQL, Qdrant y los archivos**; el manifiesto lo declara. Si hay ingestión en curso, el catálogo, originales y vectores pueden no coincidir; restauración compara recuentos y archivos.
- Hindsight vive en `%USERPROFILE%\.pg0\instances\hindsight\data`, con la instancia `hindsight`, base de datos `hindsight` y PostgreSQL 18. No se copia su directorio de datos activo. `pg_dump` usa un snapshot PostgreSQL exportado; los estados `pending`/`processing` quedan en el dump y se reportan. La restauración de prueba no arranca Hindsight workers: hay que revisar trabajos pendientes antes de conectar la API.
- `-SkipMemory` deja `memory.state=omitted_explicitly`, `recoverable=false` y muestra una advertencia amarilla. Esa copia no recupera todas las partes de Alice y Restore-Alice no la declara completa.
- `-Online`: no detiene la API; la consistencia entre colecciones es igual de independiente.

## Restauración

```powershell
.\scripts\windows\Restore-Alice.ps1 -Backup backups\alice-20260922-233933 -Destination 'D:\restore prueba'
```

1. Valida `manifest.json` y el SHA256 de cada archivo. Cualquier diferencia aborta antes de escribir nada (exit 2).
2. Normaliza la ruta final de Windows, rechaza junctions/reparse points y rutas dentro de la instalación o cualquiera de los worktrees Git conocidos. El destino debe no existir o estar vacío. La restauración de validación no puede escribir en ninguna instalación Alice; `-Force` no anula esta salvaguarda.
3. Copia SQLite y `data\`.
4. Arranca un `qdrant.exe` temporal (el binario fijado de `infra\bin`) en 127.0.0.1:6343 con almacenamiento en `<destino>\storage\qdrant`, sube cada snapshot (`/snapshots/upload?priority=snapshot`), compara los puntos con el manifiesto y lo detiene (`-KeepQdrant` lo deja en marcha). Nunca toca el Qdrant activo.
5. Hindsight, si está incluido: comprueba checksum; inicia un cluster PostgreSQL temporal solo en loopback y bajo el destino vacío; restaura el dump, compara tablas, recuentos y estados de trabajos; detiene el cluster. No inicia Hindsight ni su cola.
6. Verifica: recuentos SQLite = manifiesto; filas de `chunks` = suma de `documents.chunks` (documentos `ready`) = puntos de `alice_chunks`; cada `documents.stored_path` existe en `data\`.

Códigos de salida: 0 restaurado y verificado, 1 verificación fallida (también copia parcial/no recuperable), 2 backup inválido, componentes faltantes o salvaguarda.

Los binarios PostgreSQL compatibles con la versión origen y `-MemoryPgBin` son requisito para verificar/restaurar Hindsight. La base instalada usa PostgreSQL 18; el backend no copia contraseñas del perfil ni las imprime. No declarar probado un restore de memoria si falla la suite de PostgreSQL aislada.

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

## Validación de memoria aislada (2026-09-30)

`tests/unit/test_backup_memory.py::test_real_postgres_snapshot_and_isolated_restore` → **1 passed** con PostgreSQL 18.1. La prueba crea dos clusters temporales y tablas sintéticas; comprueba el snapshot exportado, el dump, los recuentos y estados de trabajos tras restaurar, y que el cluster restaurado quede detenido sin workers. No conecta ni modifica la instancia real de Hindsight. Los scripts PowerShell también pasaron el análisis de sintaxis; falta ejecutar el ciclo completo de `Backup-Alice.ps1` offline contra los servicios Alice.
