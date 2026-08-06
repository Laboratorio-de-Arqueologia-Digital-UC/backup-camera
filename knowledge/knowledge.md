# Knowledge Base: Backup Camera

> **Mapa de documentación.** Este archivo recoge decisiones técnicas y errores
> resueltos, y está dirigido a quien desarrolla o mantiene el sistema.
> Para **operarlo** (preparar discos, respaldar, verificar) el material es
> `docs/GUIA_PRIMEROS_PASOS.md` y `docs/CHECKLIST_TERRENO.md`.
> Al cambiar un comportamiento que el operador percibe, actualice también esa
> guía: es la única que se lee con una tarjeta SD en la mano.

## 1. Development Workflow

### Commit Strategy (Commitizen)
Values standardized commit messages to ensure clean history and automated changelogs.
- **Tool**: `commitizen`
- **Command**: `uv run cz commit`
- **Convention**: Conventional Commits (e.g., `fix: ...`, `feat: ...`, `chore: ...`).

### Release Automation
- **Versioning**: Semantic Versioning managed by `pyproject.toml`.
- **Build System**: `build.py` automatically reads the version and names the artifact `BackupCamera_vX.Y.Z.exe`.
- **CI/CD**:
    - **Trigger**: Pushing a tag (`git tag v3.0.0` -> `git push origin v3.0.0`).
    - **Action**: `.github/workflows/release.yml` builds the executable and creates a GitHub Release with the artifact.

## 1. Project Overview & Architecture

**Backup Camera** is a forensic data ingestion tool designed to secure the chain of custody for archaeological photography.

### Architecture
- **Framework**: Python 3.9+ with `CustomTkinter` for UI.
- **Concurrency Model**: Multithreaded (UI + Monitor Thread + Worker Thread).
- **Core Libraries**:
    - `wmi`: For low-level hardware serial number extraction.
    - `blake3`: For cryptographic hashing (faster than SHA-256).
    - `shutil`: For optimized file operations.

### Critical Logic: "Quadruple Hop" (Updated v3.1)
The system strictly enforces a four-step process for total traceability:
1.  **Ingest**: SD Card -> Local SSD (Verification + Hashing).
2.  **Backup**: Local SSD -> External Drive (Cloning).
3.  **Archive**: External Drive -> Final Storage (Audit + Integrity Check).

> [!NOTE]
> **Safety Mechanism**: External drives are ONLY recognized if they contain a root file named `.backup_drive`. This prevents accidental cloning to the wrong drive.

### Bridge Mode (Chunked Processing)
Introduced in v1.1.0 to handle scenarios where `Size(SD Card) > FreeSpace(Internal Disk)`.

**Logic Flow:**
1.  **Analysis**: Compares Total Source Size vs. Internal Free Space.
2.  **Strategy Selection**:
    -   **Persistent Copy**: If Internal Space > Source Size, performs a full copy and **keeps** the internal copy (3 copies total: SD, Int, Ext).
    -   **Volatile Copy (Chunking)**: If Internal Space is low, copies in ~5GB chunks.
        -   `SD -> Internal (Temp) -> Verify Hash`
        -   `Internal (Temp) -> External -> Verify Hash`
        -   `Delete Internal (Temp)`
3.  **Safety**: Always preserves a 2GB buffer on the internal OS drive.

### Final Archive Module (v3.1)
Introduced to close the cycle from Field to Lab/Server.
-   **Input**: External Drives (with `.backup_drive` and `Backup_Ingesta` folder).
-   **Output**: Network Storage / Final Deposit.
-   **Validation**:
    -   Does NOT re-hash blindly.
    -   Calculates the hash of the file arriving at the Final Storage.
    -   Compares it against the **Original Manifest** created during Ingest.
    -   **Outcome**: Generates an `audit_log.txt` certifying that the file on the Server is bit-exact to the file that left the SD Card.

### Stage-Agnostic Entry & Adoption (v3.2)

**Problema**: el flujo asumía que todo proceso empieza en la tarjeta SD. En la
práctica, buena parte del material ya fue respaldado y copiado **a mano** hasta
un SSD, con una estructura propia (habitualmente una carpeta por pieza). Esas
copias no podían entrar al flujo por tres razones acumuladas:

1. `manifest.json` solo se generaba dentro de `IngestWorker`.
2. `ArchiveWorker` descartaba en silencio (`continue`) toda carpeta sin
   manifiesto, terminando con "0 sesiones procesadas" sin explicación.
3. La habilitación de botones dependía del hardware conectado (ID WMI de la SD
   o marcador `.backup_drive`), no de los datos disponibles.

**Solución**: `src/lib_adopt.py` construye una **línea base de integridad**
retroactiva sobre datos ya copiados: recorre los archivos, calcula BLAKE3 en
streaming y escribe `manifest.json` + `hashes_blake3.json`, sin mover, copiar
ni modificar nada.

#### Decisión de diseño: cadena de custodia parcial

Un manifiesto adoptado **no puede** certificar equivalencia bit-exacta con la
tarjeta SD, porque la copia ocurrió fuera del sistema: solo certifica que los
datos no han cambiado **desde el momento de la adopción**. Reutilizar el texto
original del `audit_log.txt` habría convertido la auditoría en una afirmación
falsa, que es el peor resultado posible en una herramienta forense.

Por eso el esquema de manifiesto se versionó (`schema_version: 2`) y declara su
naturaleza de forma explícita:

| Campo | Ingesta desde SD | Copia adoptada |
|---|---|---|
| `origin` | `sd_ingest` | `manual_adopted` |
| `chain_of_custody` | `full` | `partial` |
| `hardware_id` | serial WMI | `null` |
| `adopted_at` / `adopted_by` | ausente | fecha y operador |

Los manifiestos antiguos sin estas claves se tratan como `legacy_unknown` y se
siguen procesando con normalidad.

**Invariantes que el módulo garantiza:**
- **Idempotencia**: si ya existe un manifiesto adoptado, la operación por
  defecto es *verificar* (re-hashear y reportar archivos modificados,
  faltantes o nuevos), nunca reescribir.
- **Protección de la custodia completa**: un manifiesto con `origin` distinto
  de `manual_adopted` no se sobrescribe jamás, ni con `force=True`. Degradar
  `full` a `partial` sería una pérdida irreversible de información.
- **No destructividad**: la adopción solo agrega dos archivos de control.
- **Aislamiento por sesión**: un archivo ilegible reporta esa sesión como
  `error` y el recorrido continúa. Perder 39 piezas por culpa de la número 12
  sería inaceptable en un contexto donde cada corrida dura horas.

#### Colisión de basenames en `hashes_blake3.json`

`save_hashes_blake3` aplana las claves a `os.path.basename(path)` por
compatibilidad con `fotogrametria-pipeline` (contrato verificado en
`tests/test_hashes.py`). En una estructura por pieza es frecuente que varias
subcarpetas contengan el mismo nombre de archivo (`IMG_0001.CR2`), en cuyo caso
**solo sobrevive el último hash**. No se cambió el formato para no romper la
etapa siguiente; en su lugar `lib_adopt` detecta los nombres repetidos, los
incluye en el reporte (`duplicate_basenames`) y los expone en la GUI y el CLI.
El `manifest.json` conserva la ruta relativa completa y es la fuente de verdad
para la auditoría. Adoptar **por pieza** evita el problema, porque cada pieza
pasa a ser una sesión independiente con su propio mapa de hashes.

#### Otra distinción importante

`scripts/generate_blake3_hashes.py` **no** sirve para adoptar: solo re-deriva el
mapa plano de hashes a partir de un `manifest.json` existente y nunca lee los
bytes de los archivos. La adopción hace lo contrario: parte de los bytes para
crear el manifiesto que no existe.

#### Estado por etapa en la GUI

`BackupCameraApp.stage_ready` (`source`, `local`, `external`, `archive`) es
ahora la única fuente para habilitar botones, junto con un flag `busy` que los
bloquea durante una operación. Esto es imprescindible porque `MonitorThread`
refresca la UI cada 2 segundos y, sin el flag, reactivaría botones en medio de
una copia.

## 2. Environment & Tooling (UV)

This project is developed in a **UV (Ultraviolet)** Python environment. This is the primary tool for dependency resolution and execution.

### Dependency Management
- **Manifest**: `pyproject.toml` is the source of truth.
- **Virtual Environment**: Use `uv venv` to create.
- **Installation**: Use `uv pip install -e .` (editable install recommended).
- **Updates**: Use `uv sync` to align environment with lockfile.
- **Execution**: ALWAYS run scripts via `uv run python <script.py>` to ensure the virtual environment context is loaded correctly, especially for `wmi` and `tkinter` bindings.

### Build System
- **Tool**: `PyInstaller`.
- **Command**: `uv run python build.py` (or `python build.py` if the venv is activated).
- **Configuration**:
    - `--noconsole`: Hides terminal for end-users.
    - `--onefile`: Distribution ease.
    - `--add-data`: Required for bundling `CustomTkinter` assets inside the frozen EXE.

## 3. Learnings & Error Log

### [Insight] Commitizen in Automated/Agentic Environments
**Context**: Executing `uv run cz commit` implicitly triggers an interactive terminal UI (arrows/selection).
**Constraint**: When run by autonomous agents, scripts without a real TTY, or CI/CD pipelines, this interactive prompt blocks execution indefinitely and causes process freezing.
**Solution**: 
1. Use explicit messaging to bypass the prompt: `uv run cz commit --message "feat: description" -m "extended..."`.
2. Standard `git commit -m "..."` formatted correctly is also perfectly parsed by `cz` later.
3. Avoid depending blindly on interactive commands like `cz bump` when Git histories might have been rewritten or tag states are inconsistent; use explicit version declarations instead.

### [Insight] `ruff format --check` en CI exige formato canónico exacto
**Context**: el workflow ejecuta `uv run ruff format --check .`, que falla ante
cualquier diferencia con la salida del formateador, incluso si el código es
válido y legible.
**Casos que rompen el check sin ser errores de estilo evidentes**:
1. Una llamada partida en varias líneas **sin coma final** cuya versión de una
   sola línea cabe en 88 columnas: el formateador la colapsa.
2. Paréntesis redundantes alrededor de una cadena que cabe en una línea
   (`x = (\n    "texto"\n)`): se eliminan.
3. Llamadas anidadas cuyo argumento interno cabe en la línea del padre: se
   reindentan.
4. Desestructuración de tupla con paréntesis en el lado derecho.
**Solución**: usar la **coma final mágica** en toda construcción multilínea que
se quiera mantener explotada, y extraer expresiones anidadas a variables
intermedias en lugar de anidar llamadas partidas.

### [Error] PyInstaller Module Not Found
**Context**: Attempted to run `python build.py` immediately after coding.
**Error**: `ModuleNotFoundError: No module named 'PyInstaller'`.
**Cause**: The environment where the command was executed did not have the dependencies installed, or the shell was not using the correct `uv` managed virtual environment.
**Fix**: Ensure `uv pip install pyinstaller` is run, and execute via `uv run python build.py`.

### [Insight] WMI Permissions
**Details**: The `wmi` library queries `Win32_PhysicalMedia` or `Win32_DiskDrive`.
**Constraint**: On some Windows configurations, accessing serial numbers via WMI requires **Administrator Privileges**. The final EXE should be set to "Run as Administrator" in its manifest to avoid "Permission Denied" or empty serial returns.

### [Insight] CustomTkinter Threading
**Details**: Updating UI elements (Labels, Progress Bars) **must** happen on the Main Thread.
**Solution**: Use `self.after(0, lambda: ...)` pattern to marshal updates from Worker Threads (`MonitorThread`, `IngestWorker`) back to the GUI loop. Direct calls from threads causes crashes or "Not Responding" states.

### [Insight] La detección de discos externos elige la letra menor
**Details**: `MonitorThread.check_external_targets` recorre `A:` a `Z:` buscando
el marcador y `_update_backup_ui` toma `drives[0]`. Con dos discos marcados
conectados a la vez, gana el de letra alfabéticamente menor, que puede no ser
el deseado.
**Mitigación**: la selección manual (`Elegir destino...`) tiene prioridad sobre
la detección automática. Documentado en la guía operativa.

### [Insight] El respaldo a externo omite, no completa
**Details**: `BackupWorker` salta las carpetas que ya existen en el destino
(`if not os.path.exists(d)`), por política de no sobrescribir a ciegas.
**Consecuencia práctica**: una carpeta copiada a medias por una desconexión no
se repara sola. Hay que eliminarla o renombrarla antes de reintentar.
**Pendiente**: un modo diferencial real (comparar tamaño/hash por archivo)
resolvería esto; ver sección 4.

## 4. Pending Improvements
- **Differential Backup**: Currently, the backup to external drive is a simple "Copy Tree". Implementing `rsync`-like behavior (checking size/time/hash) would improve speed for incremental backups and permitiría **completar** carpetas parcialmente copiadas.
- **PDF Report Generation**: Only JSON manifests are generated. A human-readable PDF report is a planned future feature.
- **Adopción recursiva**: `scan_manual_folder` solo considera el primer nivel de
  subcarpetas. Estructuras más profundas (por ejemplo, sitio/unidad/pieza)
  requieren adoptar cada nivel intermedio por separado.
- **Cancelación de ingesta y puente**: solo la adopción y el archivo final
  admiten `stop_event`. `IngestWorker` y `BridgeWorker` no se pueden detener sin
  dejar copias incompletas.
- **Caché de `stage_ready`**: `refresh_stage_state` hace `os.listdir` del
  repositorio local en cada ciclo del monitor (2 s). Sobre una ruta de red lenta
  esto introduciría latencia perceptible en la UI.

## 5. Quality Assurance & Testing

### Static Analysis
- **Tools**: `ruff` (linter/formatter) and `pyright` (type checker).
- **Configuration**:
    - `ruff`: Configured in `pyproject.toml` (or default).
    - `pyright`: Configured in `pyrightconfig.json` to handle missing stubs (e.g., `customtkinter`) by setting `reportMissingTypeStubs: false`. Note `include` only covers `src` and `build.py`, so `scripts/` and `tests/` are linted but not type-checked.
- **Insight**: los diccionarios de retorno con valores heterogéneos deben
  anotarse como `Dict[str, Any]`. Sin la anotación, pyright infiere
  `bool | list[str]` y expresiones como `len(inspect_root(x)["without_manifest"])`
  fallan con `reportArgumentType`, que es error en el modo por defecto.

### Testing Strategy
- **Unit Tests**: Located in `tests/`. Run with `uv run pytest`.
- **Scope**:
    - **Covered**: Core logic (`lib_copy`, `lib_storage`, `lib_hardware` logic), archive worker (`tests/test_archive.py`) and adoption (`tests/test_adopt.py`).
    - **Not Covered**: UI interactions (CustomTkinter) and physical WMI hardware responses (mocks required for future).
- **Pattern**: los workers reciben un doble de la app (`MockApp`) que implementa
  los callbacks (`log_message`, `archive_complete`, ...) y se ejecutan con
  `worker.run()` de forma sincrónica, sin hilos.
- **Principio**: cada prueba de `test_adopt.py` reproduce un escenario real del
  laboratorio (dos SSD con la misma pieza, un archivo bloqueado, archivos
  sueltos en la raíz), no un caso abstracto. Así la suite documenta el
  comportamiento esperado en terreno.

### [Fixed Bug] Copia destructiva cuando origen y destino coinciden
- **Symptom**: archivar una carpeta sobre sí misma dejaba los archivos
  originales en **cero bytes**, de forma irrecuperable.
- **Cause**: `secure_copy` abre el destino con `open(dst, "wb")`, que **trunca**
  el archivo antes de leer el origen. Si ambas rutas son la misma, se trunca y
  luego se lee un archivo vacío. No había ninguna validación previa.
- **Alcanzabilidad**: el defecto era latente desde v3.1, pero requería una
  coincidencia improbable de rutas. Al introducir "Elegir origen..." en la
  etapa 4 pasó a estar a un par de clics de cualquier operador.
- **Fix**: `ArchiveWorker` valida con `same_path()` tanto a nivel de raíz
  (aborta con `archive_failed`) como por sesión (omite y reporta), y `main.py`
  lo valida antes de lanzar el worker. Cubierto por dos pruebas que verifican
  que el contenido original sigue intacto.
- **Lección**: al ampliar la libertad del usuario sobre las rutas, hay que
  auditar de nuevo todas las operaciones destructivas. Una función segura bajo
  el supuesto "origen y destino siempre difieren" deja de serlo cuando ese
  supuesto se vuelve elegible.

### [Fixed Bug] `"E:"` es una ruta relativa en Windows
- **Symptom**: rutas construidas como `"E:Backup_Ingesta"` que resolvían a
  carpetas inesperadas; en el peor caso, `os.listdir("E:")` listaba el
  directorio actual de esa unidad y se archivaban datos ajenos en silencio.
- **Cause**: en Windows `"E:"` (sin barra) es **relativa al directorio actual de
  esa unidad**, que cada proceso mantiene por separado y que los diálogos de
  archivos pueden modificar. `MonitorThread` entrega los discos como `"%s:"`.
- **Fix**: `lib_storage.normalize_root()` convierte `"E:"` en `"E:\\"`. Se
  aplica en `ArchiveWorker`, `BackupWorker`, el modo puente, la detección de
  destinos y las funciones de `lib_adopt`.
- **Lección**: nunca pasar una letra de unidad a `os.path.join` sin normalizar.

### [Fixed Bug] Colisión de nombres de sesión contada como éxito
- **Symptom**: al archivar un segundo SSD que traía una carpeta con el mismo
  nombre (`Pieza_001`), la sesión se omitía, se sumaba a `processed_count` y el
  diálogo informaba "Sesiones procesadas: N". El operador creía que el dato
  estaba en el NAS.
- **Cause**: el chequeo de idempotencia (`carpeta destino existe` +
  `audit_log.txt` presente) era correcto mientras los nombres fueran
  `YYYY-MM-DD_SD-<serial>_HHMM`, únicos por construcción. Los nombres adoptados
  no lo son.
- **Fix**: `_resolve_destination()` compara la **huella** del manifiesto (pares
  `(ruta, hash)` ordenados). Si coincide, es la misma sesión y se omite; si
  difiere, se archiva con sufijo `__YYYYMMDD-HHMMSS` y se reporta `CONFLICTO`.
- **Lección**: al relajar una convención de nombres, revisar todo el código que
  dependía de su unicidad como identificador.

### [Fixed Bug] UI Class Scope & Inheritance
- **Symptom**: `AttributeError: '_tkinter.tkapp' object has no attribute 'on_source_select'` at startup.
- **Cause**: The `BackupWorker` class was defined *inside* the body of `BackupCameraApp` (Python indentation error). This caused `BackupCameraApp` methods defined after `BackupWorker` to be lost or mis-scoped.
- **Fix**: Moved `BackupWorker` class definition to the top of the file, outside of `BackupCameraApp`.
- **Lesson**: Be extremely careful with indentation when defining multiple classes in a single file.

### [Fixed Bug] WMI in Threads
- **Symptom**: `SyntaxError` from WMI when running in `MonitorThread`.
- **Cause**: WMI uses COM, which must be initialized in every new thread on Windows.
- **Fix**: Added `import pythoncom` and called `pythoncom.CoInitialize()` at the start of `MonitorThread.run()`.

### [Fixed Bug] Pyright in CI
- **Symptom**: 9000+ errors in CI/CD from `.venv` files.
- **Cause**: `uv run pyright .` forced scanning of all directories including virtual environments.
- **Fix**: 
    1. Added `.venv`, `build`, `dist` to `pyrightconfig.json` excludes.
    2. Changed CI command to `uv run pyright` (no dot) to respect the config file's `include` paths.

### [Fixed Bug] PyInstaller Relative Paths
- **Symptom**: `Unable to find '.../build/src'` during build.
- **Cause**: Setting `--specpath=build` changes the working directory for relative paths in `.spec` files. A command like `--add-data=src;.` then looks for `src` *inside* `build/`.
- **Fix**: Removed `--add-data=src;.` as it was redundant (PyInstaller automatically collects imported code). For non-code assets, absolute paths or careful relative pathing (e.g. `../src`) is required when spec is moved.

### [Fixed Bug] Mensaje de estado falso tras error de archivo
- **Symptom**: al fallar el archivo final, el panel de ingesta mostraba
  "¡Ingesta Completada!".
- **Cause**: `_archive_failed_ui` terminaba con dos líneas huérfanas
  (`option_source.configure(...)` y `lbl_status.configure(...)`) que
  pertenecían a `_ingest_complete_ui`.
- **Fix**: se reubicaron en su método correcto. En una herramienta forense un
  mensaje de éxito falso es un defecto grave, no cosmético.
