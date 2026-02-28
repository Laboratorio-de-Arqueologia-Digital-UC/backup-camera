## v3.1.1 (2026-02-27)

### Style
- **lint**: apply ruff formatting across codebase
- **deps**: bump ruff to 0.14.11

## v3.1.0 (2026-02-19)

### Feat
- **archive**: implement Final Archive module and 4-column UI
- **fix**: bridge pathing and naming improvements
- **docs**: update version references

## v3.0.0 (2026-01-13)

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

### 🚀 Mejoras (Improvements)

*   **Verificación Robusta de Espacio en Modo Puente**: Ahora el sistema de ingestión verifica el espacio desde la raíz de la unidad destino evitando generar carpetas vacías antes de procesarse y corrigiendo el reporte de "Error verificando disco externo".
*   **Protección Avanzada Modo Puente**: Se añadió un sistema de evitación de caídas del OS al impedir procesar archivos individuales unitarios que sean de un tamaño mayor al almacenamiento interno de puente libre disponible.
*   **Extracción de EXIF Paralelizada**: El cálculo de metadatos EXIF se ha trasladado a un ThreadPoolExecutor, incrementando la velocidad de verificación notablemente.

### Fix

- **correccion-de-commitizen**: correccion de commitizen en pyproject.toml
- **correcion-de-botones**: correccion de botones en gui
