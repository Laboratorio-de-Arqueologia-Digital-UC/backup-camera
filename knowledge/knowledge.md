# Knowledge Base: Backup Camera

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

#### Colisión de basenames en `hashes_blake3.json`

`save_hashes_blake3` aplana las claves a `os.path.basename(path)` por
compatibilidad con `fotogrametria-pipeline` (contrato verificado en
`tests/test_hashes.py`). En una estructura por pieza es frecuente que varias
subcarpetas contengan el mismo nombre de archivo (`IMG_0001.CR2`), en cuyo caso
**solo sobrevive el último hash**. No se cambió el formato para no romper la
etapa siguiente; en su lugar `lib_adopt` detecta los nombres repetidos y emite
un `logging.warning`. El `manifest.json` conserva la ruta relativa completa y
es la fuente de verdad para la auditoría.

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

## 4. Pending Improvements
- **Differential Backup**: Currently, the backup to external drive is a simple "Copy Tree". Implementing `rsync`-like behavior (checking size/time/hash) would improve speed for incremental backups.
- **PDF Report Generation**: Only JSON manifests are generated. A human-readable PDF report is a planned future feature.
- **Adopción recursiva**: `scan_manual_folder` solo considera el primer nivel de
  subcarpetas. Estructuras más profundas (por ejemplo, sitio/unidad/pieza)
  requieren adoptar cada nivel intermedio por separado.

## 5. Quality Assurance & Testing

### Static Analysis
- **Tools**: `ruff` (linter/formatter) and `pyright` (type checker).
- **Configuration**:
    - `ruff`: Configured in `pyproject.toml` (or default).
    - `pyright`: Configured in `pyrightconfig.json` to handle missing stubs (e.g., `customtkinter`) by setting `reportMissingTypeStubs: false`. Note `include` only covers `src` and `build.py`, so `scripts/` and `tests/` are linted but not type-checked.

### Testing Strategy
- **Unit Tests**: Located in `tests/`. Run with `uv run pytest`.
- **Scope**:
    - **Covered**: Core logic (`lib_copy`, `lib_storage`, `lib_hardware` logic), archive worker (`tests/test_archive.py`) and adoption (`tests/test_adopt.py`).
    - **Not Covered**: UI interactions (CustomTkinter) and physical WMI hardware responses (mocks required for future).
- **Pattern**: los workers reciben un doble de la app (`MockApp`) que implementa
  los callbacks (`log_message`, `archive_complete`, ...) y se ejecutan con
  `worker.run()` de forma sincrónica, sin hilos.

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
