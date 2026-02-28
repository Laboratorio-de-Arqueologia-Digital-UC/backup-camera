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
*   **Identificación de Hardware Universal (WMI):** Vincula los datos al número de serie físico, soportando tanto USB como lectores internos (PCIe/SCSI) y detectando tipos de tarjeta (SD, SDXC, MicroSD).
*   **Hashing al Vuelo (BLAKE3):** Verifica la integridad de cada byte copiado sin sacrificar velocidad.
*   **Protocolo de Cuatro Pasos:** Flujo de trabajo seguro: SD -> Local -> Externo -> Archivo Final (Servidor/NAS).
*   **Modo Puente (Bridge):** Permite la copia desde SD a Disco Externo utilizando el disco interno como búfer temporal inteligente/volátil, ideal para equipos con poco espacio de almacenamiento.

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
dist/BackupCamera_v3.1.2.exe
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
2.  **Columna 2:** "INICIAR COPIA". Ingesta verificada a repositorio local.
3.  **Columna 3:** Conecte disco externo (con archivo `.backup_drive`). "CLONAR".
4.  **Columna 4:** Seleccione ruta final (ej. `Z:\Proyecto`). "ARCHIVAR Y VALIDAR".
    -   El sistema verificará que los datos en `Z:\` coincidan exactamente con el `manifest.json` original de la tarjeta SD.



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
2.  Cree un tag en git: `git tag v3.1.2` (debe coincidir con la versión).
3.  Empuje el tag: `git push origin v3.1.2`.
4.  GitHub Actions generará automáticamente el ejecutable `BackupCamera_v3.1.2.exe` y lo publicará en la sección **Releases**.

## ✍️ Autores

*   **Laboratorio de Arqueología Digital UC** - *Desarrollo Inicial*
