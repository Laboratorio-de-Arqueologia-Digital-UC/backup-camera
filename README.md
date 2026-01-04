# Backup Camera

![License](https://img.shields.io/badge/license-Apache%202.0-blue) ![Python](https://img.shields.io/badge/python-3.9+-green) ![Platform](https://img.shields.io/badge/platform-windows-lightgrey)

> Sistema de ingesta forense de datos para contextos arqueológicos, garantizando la Cadena de Custodia Digital mediante verificación de hardware y hashing criptográfico.

## 📋 Tabla de Contenidos
- [Descripción](#-descripción)
- [Instalación](#-instalación)
- [Uso](#-uso)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Tecnologías](#-tecnologías)
- [Contribución](#-contribución)
- [Licencia](#-licencia)
- [Autores](#-autores)

## 🚀 Descripción
En la fotogrametría arqueológica, la integridad de los datos es crítica. **Backup Camera** elimina la incertidumbre en el proceso de descarga de tarjetas de memoria, transformando una copia simple en un proceso auditado.

**Características Clave:**
*   **Identificación de Hardware (WMI):** Vincula los datos al número de serie físico de la tarjeta SD, no a la letra de la unidad.
*   **Hashing al Vuelo (BLAKE3):** Verifica la integridad de cada byte copiado sin sacrificar velocidad.
*   **Protocolo de Doble Salto:** Fuerza un flujo de trabajo seguro: Tarjeta SD -> SSD Local -> Disco Externo (Redundancia).

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
dist/BackupCamera.exe
```

### Flujo de Trabajo
1.  **Panel 1 (Naranja - Origen):** Inserte la tarjeta SD. El sistema validará su ID de hardware automáticamente.
2.  **Panel 2 (Azul - Ingesta):** Presione "INICIAR COPIA". Los datos se transfieren y verifican al repositorio local.
3.  **Panel 3 (Verde - Respaldo):** Conecte el disco externo.
    > **IMPORTANTE:** El disco externo DEBE tener un archivo vacío llamado `.backup_drive` en su raíz para ser detectado (medida de seguridad).
    Presione "CLONAR".

## 📂 Estructura del Proyecto

```text
/
├── src/                 # Código fuente principal
│   ├── lib_hardware.py  # Lógica WMI y detección de discos
│   ├── lib_copy.py      # Motor de copia segura con BLAKE3
│   ├── lib_storage.py   # Gestión de rutas y espacio
│   └── main.py          # Interfaz gráfica (CustomTkinter)
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

## ✍️ Autores

*   **Laboratorio de Arqueología Digital UC** - *Desarrollo Inicial*
