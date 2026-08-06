## v3.2.0 (2026-08-06)

### Feat

- **adopt**: permitir ingresar al flujo en cualquier etapa mediante la
  adopcion de copias hechas manualmente (`src/lib_adopt.py`)
- **ui**: boton "ADOPTAR CARPETA EXISTENTE", seleccion manual del destino
  externo y seleccion libre del origen del archivo final
- **ui**: la habilitacion de cada etapa depende de los datos disponibles en
  disco (`stage_ready`) y ya no del hardware conectado
- **ui**: boton Cancelar para las operaciones que admiten detencion segura
- **archive**: origenes flexibles (raiz con sesiones, `Backup_Ingesta` o una
  sesion individual) y reporte de carpetas omitidas por falta de manifiesto
- **archive**: `audit_log.txt` declara el origen y no afirma equivalencia
  bit-exacta con la SD cuando la sesion fue adoptada
- **adopt**: reporte de archivos sueltos en la raiz y de colisiones de
  nombre en `hashes_blake3.json`
- **cli**: `scripts/adopt.py` para operar sin interfaz grafica

### Fix

- **archive**: rechazar que el origen y el destino sean la misma carpeta.
  `secure_copy` abre el destino con "wb", que truncaba el archivo a cero
  bytes antes de leer el origen: el dato original se perdia de forma
  irreversible. Se valida a nivel de raiz y por sesion.
- **storage**: normalizar las raices de unidad (`"E:"` -> `"E:\"`). En
  Windows `"E:"` es relativa al directorio actual de esa unidad, por lo que
  las rutas derivadas apuntaban a carpetas arbitrarias.
- **archive**: detectar colisiones de nombre de sesion en el destino
  comparando la huella del manifiesto. Antes, una segunda sesion distinta
  con el mismo nombre se omitia y se contaba como archivada.
- **adopt**: aislar los errores por sesion; un archivo ilegible ya no aborta
  la corrida completa
- **adopt**: permitir cancelar la adopcion (`stop_event`)
- **ui**: `_archive_failed_ui` mostraba "Ingesta Completada" tras un error
- **ui**: se eliminan el `btn_bridge` duplicado y huerfano de `frame_dest`
- **ui**: `backup_target` se inicializa, evitando `AttributeError`

### Docs

- agregar `docs/GUIA_PRIMEROS_PASOS.md` y `docs/CHECKLIST_TERRENO.md` para
  personas que se incorporan al respaldo
- documentar la cadena de custodia parcial, los limites de la adopcion y los
  comportamientos que sorprenden en la practica

## v3.1.3 (2026-04-21)

### Feat

- **ui**: show completion dialog after ingest and bridge copy

### Fix

- **ci**: apply ruff formatting and add pyright venv resolution

## v3.1.2 (2026-02-27)

### Fix

- **bridge**: implement robust drive storage verification and chunk failure prevention

## v3.1.1 (2026-02-27)

### Feat

- implement Final Archive module, 4-column UI, and update docs (v3.1.0)

### Fix

- **style**: hashing
- **feat**: hashing
- **bridge**: fix bridge pathing, naming, and add enhanced recovery script
- **bridge**: resolve misplaced paths, unify naming, and add recovery script
- resolve undefined variable in main.py and linting issues in archive module
- **documentation**: update version references to v3.0.0

## v3.0.0 (2026-01-13)

### BREAKING CHANGE

-  to support internal PCIe/SCSI SD readers by

### Fix

- **implementation-for-robust-memory-card-detection**: feat(hardware): support for internal SD readers and card type detection

## v2.0.2 (2026-01-10)

### Fix

- **env**: update uv.lock to match current environment

## v2.0.1 (2026-01-10)

### Fix

- **gui**: resolve ruff and pyright style errors

## v2.0.0 (2026-01-10)

### Fix

- **new-method**: new method

## v1.1.0 (2026-01-04)

### Feat

- add a comprehensive knowledge base document detailing project architecture, development workflow, and tooling.
- add initial GUI application for forensic camera data ingestion and backup management.
- implement initial backup camera application including GUI, background workers, and core modules for hardware, copying, and storage management.

## v1.0.0 (2026-01-04)

### Fix

- **correccion-de-commitizen**: correccion de commitizen en pyproject.toml
- **correcion-de-botones**: correccion de botones en gui
