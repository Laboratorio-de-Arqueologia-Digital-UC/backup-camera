# Backup Camera

![License](https://img.shields.io/badge/license-Apache%202.0-blue) ![Python](https://img.shields.io/badge/python-3.9+-green) ![Platform](https://img.shields.io/badge/platform-windows-lightgrey) ![CI](https://github.com/Laboratorio-de-Arqueologia-Digital-UC/backup-camera/actions/workflows/ci.yml/badge.svg)

> Sistema de ingesta forense de datos para contextos arqueológicos, garantizando la Cadena de Custodia Digital mediante verificación de hardware y hashing criptográfico.

## 📋 Tabla de Contenidos
- [Descripción](#-descripción)
- [Instalación](#-instalación)
- [Uso](#-uso)
- [Ingreso al flujo en cualquier etapa](#-ingreso-al-flujo-en-cualquier-etapa)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Tecnologías](#-tecnologías)
- [Contribución](#-contribución)
- [Licencia](#-licencia)
- [Autores](#-autores)

## 🚀 Descripción
En la fotogrametría arqueológica, la integridad de los datos es crítica. **Backup Camera** elimina la incertidumbre en el proceso de descarga de tarjetas de memoria, transformando una copia simple en un proceso auditado.

**Características Clave:**
*   **Identificación de Hardware Universal (WMI):** Vincula los datos al número de serie físico, soportando tanto USB como lectores internos (PCIe/SCSI) y detectando tipos de tarjeta (SD, SDXC, MicroSD).
*   **Hashing al Vuelo (BLAKE3):** Verifica la integridad de cada byte copiado sin sacrificar velocidad.
*   **Protocolo de Cuatro Pasos:** Flujo de trabajo seguro: SD -> Local -> Externo -> Archivo Final (Servidor/NAS).
*   **Ingreso en Cualquier Etapa (v3.2):** Permite adoptar copias que ya fueron hechas manualmente y engancharlas a las etapas 3 y 4, sin necesidad de la tarjeta SD original.
*   **Modo Puente (Bridge):** Permite la copia desde SD a Disco Externo utilizando el disco interno como búfer temporal inteligente/volátil, ideal para equipos con poco espacio de almacenamiento.
*   **Notificaciones de Finalización:** Al completar cualquier operación de copia (ingesta, puente, respaldo o archivo), se muestra un diálogo con resumen detallado: sesión, archivos copiados, tamaño total, destino y hora de finalización.

## 🛠️ Instalación

### Pre-requisitos
*   Windows 10/11 (Requerido para acceso WMI).
*   Python 3.9 o superior.
*   Gestor de paquetes `uv` (recomendado) o `pip`.

### Pasos

1.  Clona el repositorio:
    ```bash
    git clone https://github.com/Laboratorio-Arqueologia/backup-camera.git
    cd backup-camera
    ```

2.  Instala las dependencias:
    ```bash
    # Inicializa el entorno y añade dependencias
    uv venv
    uv pip install -e .
    # O si usas el lockfile:
    # uv sync
    ```

3.  (Opcional) Genera el ejecutable:
    ```bash
    uv run python build.py
    ```

## 💻 Uso

El sistema está diseñado con una interfaz de "Semáforo" de 3 paneles.

### Ejecución
```bash
# Ejecutar desde código fuente con uv (Recomendado)
uv run python src/main.py

# O ejecutando el binario generado en /dist
dist/BackupCamera_v3.2.0.exe
```

### Interfaz Renovada (v3.1)
El sistema presenta una interfaz panorámica de **4 Columnas**:
1.  **Origen (Naranja):** Detección de Tarjetas SD.
2.  **Ingesta (Azul):** Transferencia segura a PC Local.
3.  **Respaldo (Verde):** Clonación a Disco Externo.
4.  **Archivo Final (Púrpura):** Auditoría y transferencia a Servidor/NAS.

### Nivel "Modo Puente" (Mejorado v3.1.2)
Se activa automáticamente cuando el espacio en disco local es insuficiente. Permite la copia segura desde SD a Disco Externo utilizando el disco interno como búfer temporal volátil fragmentado.
**Seguridad Garantizada:** El sistema verifica recursivamente el tamaño del disco raíz y previene cuelgues del SO evaluando que ningún archivo individual sobrepase el espacio libre seguro.

### Flujo de Trabajo
1.  **Columna 1:** Inserte la tarjeta SD. El sistema valida ID de hardware.
2.  **Columna 2:** "INICIAR COPIA". Ingesta verificada a repositorio local. Al finalizar, aparece un diálogo de confirmación con resumen de la sesión.
3.  **Columna 3:** Conecte disco externo (con archivo `.backup_drive`). "CLONAR". Al finalizar, aparece un diálogo de confirmación.
4.  **Columna 4:** Seleccione ruta final (ej. `Z:\Proyecto`). "ARCHIVAR Y VALIDAR". Al finalizar, aparece un diálogo de confirmación.
    -   El sistema verificará que los datos en `Z:\` coincidan exactamente con el `manifest.json` original de la tarjeta SD.

## 🔀 Ingreso al flujo en cualquier etapa

No todo el material llega desde una tarjeta SD recién insertada. Es habitual que el respaldo y la copia **ya se hayan hecho manualmente hasta un SSD**, con una estructura propia (por ejemplo, una carpeta por pieza). Antes esas copias no podían entrar al flujo: sin `manifest.json` el módulo de archivo las omitía en silencio.

La **adopción** resuelve esto: recorre los archivos ya copiados, calcula su hash BLAKE3 y escribe la línea base de integridad (`manifest.json` + `hashes_blake3.json`) **sin mover, copiar ni modificar nada**.

### Desde la interfaz

*   **Etapa 2 → "ADOPTAR CARPETA EXISTENTE"**: elija la carpeta e indique si cada subcarpeta es una sesión (caso "por pieza") o si toda la carpeta es una sola sesión.
*   **Etapa 3 → "Elegir destino..."**: designa manualmente el disco de respaldo cuando no hay un `.backup_drive`, con opción de crear el marcador.
*   **Etapa 4 → "Elegir origen..."**: archiva desde cualquier ruta (SSD, disco externo o carpeta local). Si detecta carpetas sin manifiesto, ofrece adoptarlas antes de continuar.

Los botones de cada etapa se habilitan según **los datos que existen en disco**, no según el hardware conectado.

### Desde la línea de comandos

```bash
# Adoptar una copia manual organizada por pieza
uv run python scripts/adopt.py --root "D:\Piezas" --mode per-piece \
    --operator "Nombre Apellido" --notes "Respaldo manual de terreno"

# Tratar toda la carpeta como una sola sesión
uv run python scripts/adopt.py --root "D:\Entrega" --mode single

# Verificar integridad más tarde (no escribe; exit code 1 si hay desvíos)
uv run python scripts/adopt.py --root "D:\Piezas" --verify
```

### Cadena de custodia parcial

Una copia hecha fuera del sistema **no puede** certificarse como bit-exacta respecto de la tarjeta original. Por honestidad forense, la adopción es explícita al respecto:

| | Ingesta desde SD | Copia adoptada |
|---|---|---|
| `origin` | `sd_ingest` | `manual_adopted` |
| `chain_of_custody` | `full` | `partial` |
| `hardware_id` | serial WMI | `null` |
| `audit_log.txt` | "Verified against original manifest hashes" | "Verificado contra línea base adoptada" + advertencia |

La adopción es **idempotente**: si la sesión ya tiene manifiesto adoptado, la segunda pasada solo verifica y reporta archivos modificados, faltantes o nuevos. Un manifiesto generado por una ingesta real desde SD **nunca** se sobrescribe, ni con `--force`.

## 📂 Estructura del Proyecto

```text
/
├── src/                 # Código fuente principal
│   ├── lib_hardware.py  # Lógica WMI y detección de discos
│   ├── lib_copy.py      # Motor de copia segura y hashing con BLAKE3
│   ├── lib_storage.py   # Gestión de rutas y espacio
│   ├── lib_bridge.py    # Modo puente SD -> Interno -> Externo
│   ├── lib_archive.py   # Módulo de archivo final con auditoría
│   ├── lib_adopt.py     # Adopción de copias manuales (ingreso por etapa)
│   └── main.py          # Interfaz gráfica (CustomTkinter)
├── scripts/             # Utilidades de operación y recuperación
│   └── adopt.py         # CLI de adopción sin interfaz gráfica
├── tests/               # Suite de pruebas unitarias (pytest)
├── knowledge/           # Base de conocimientos y documentación técnica
├── .github/             # Configuraciones CI/CD y Templates
├── build.py             # Script de construcción PyInstaller
├── pyproject.toml       # Definición de dependencias
└── README.md            # Este archivo
```

## 🛠️ Tecnologías

*   **Lenguaje:** Python 3.9+
*   **GUI:** [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) (Diseño moderno High-DPI)
*   **Core:**
    *   `wmi`: Interacción de bajo nivel con el hardware de almacenamiento.
    *   `blake3`: Hashing criptográfico de alto rendimiento.
*   **Build:** PyInstaller.

## 🤝 Contribución

Las contribuciones son bienvenidas para mejorar la seguridad o compatibilidad.

1.  Revise `CONTRIBUTING.md` para guías de estilo.
2.  Abra un "Issue" para discutir cambios mayores.
3.  Envíe un Pull Request a la rama `main`.

## 📄 Licencia

Distribuido bajo la licencia **Apache 2.0**. Ver archivo `LICENSE` para más información.

## 🛠️ Desarrollo y Releases

### Commitizen
Este proyecto utiliza **Conventional Commits**. Para realizar cambios, utilice:
```bash
uv run cz commit
```
Siga las instrucciones interactivas para clasificar su cambio (`feat`, `fix`, `docs`, etc.).

### Releases Automáticos
Para generar una nueva versión distribuible:
1.  Actualice la versión en `pyproject.toml`.
2.  Cree un tag en git: `git tag v3.2.0` (debe coincidir con la versión).
3.  Empuje el tag: `git push origin v3.2.0`.
4.  GitHub Actions generará automáticamente el ejecutable `BackupCamera_v3.2.0.exe` y lo publicará en la sección **Releases**.

## ✍️ Autores

*   **Laboratorio de Arqueología Digital UC** - *Desarrollo Inicial*
