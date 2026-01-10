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
    - **Trigger**: Pushing a tag (`git tag v1.0.0` -> `git push origin v1.0.0`).
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

### Critical Logic: "Double Hop"
The system strictly enforces a two-step process:
1.  **Ingest**: SD Card -> Local SSD (Verification + Hashing).
2.  **Backup**: Local SSD -> External Drive (Cloning).

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

## 5. Quality Assurance & Testing

### Static Analysis
- **Tools**: `ruff` (linter/formatter) and `pyright` (type checker).
- **Configuration**:
    - `ruff`: Configured in `pyproject.toml` (or default).
    - `pyright`: Configured in `pyrightconfig.json` to handle missing stubs (e.g., `customtkinter`) by setting `reportMissingTypeStubs: false`.

### Testing Strategy
- **Unit Tests**: Located in `tests/`. Run with `uv run pytest`.
- **Scope**:
    - **Covered**: Core logic (`lib_copy`, `lib_storage`, `lib_hardware` logic).
    - **Not Covered**: UI interactions (CustomTkinter) and physical WMI hardware responses (mocks required for future).

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
