# Backup Camera

![License](https://img.shields.io/badge/license-Apache%202.0-blue) ![Python](https://img.shields.io/badge/python-3.9+-green) ![Platform](https://img.shields.io/badge/platform-windows-lightgrey) ![CI](https://github.com/Laboratorio-de-Arqueologia-Digital-UC/backup-camera/actions/workflows/ci.yml/badge.svg)

> Sistema de ingesta forense de datos para contextos arqueológicos, garantizando la Cadena de Custodia Digital mediante verificación de hardware y hashing criptográfico.

### 👋 ¿Se está incorporando al respaldo del laboratorio?

Empiece por la **[Guía de primeros pasos](docs/GUIA_PRIMEROS_PASOS.md)**: explica
cómo preparar el disco, respaldar paso a paso, qué hacer si las fotos ya se
copiaron a mano y cómo comprobar que un respaldo está realmente completo antes
de formatear una tarjeta. Para tener sobre la mesa: **[checklist de una
página](docs/CHECKLIST_TERRENO.md)**.

| Si usted quiere… | Lea |
|---|---|
| **Operar** el sistema (respaldar, preparar discos, verificar) | [`docs/GUIA_PRIMEROS_PASOS.md`](docs/GUIA_PRIMEROS_PASOS.md) |
| Un recordatorio breve para terreno | [`docs/CHECKLIST_TERRENO.md`](docs/CHECKLIST_TERRENO.md) |
| **Entender** las decisiones técnicas y el historial de errores | [`knowledge/knowledge.md`](knowledge/knowledge.md) |
| **Desarrollar** o contribuir | Este archivo y [`CONTRIBUTING.md`](CONTRIBUTING.md) |

## 📋 Tabla de Contenidos
- [Descripción](#-descripción)
- [Instalación](#️-instalación)
- [Uso](#-uso)
- [Ingreso al flujo en cualquier etapa](#-ingreso-al-flujo-en-cualquier-etapa)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Tecnologías](#️-tecnologías)
- [Contribución](#-contribución)
- [Licencia](#-licencia)
- [Autores](#️-autores)

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

> Para el procedimiento operativo detallado, con capturas de decisiones y
> solución de problemas, use la [Guía de primeros pasos](docs/GUIA_PRIMEROS_PASOS.md).
> Esta sección es un resumen técnico.

### Ejecución
```bash
# Ejecutar desde código fuente con uv (Recomendado)
uv run python src/main.py

# O ejecutando el binario generado en /dist
dist/BackupCamera_v3.2.0.exe
```

Ejecutar **como administrador**: sin privilegios elevados, WMI puede devolver
el número de serie de la tarjeta vacío y la etapa 1 no se habilita.

### Interfaz de 4 Columnas
1.  **Origen (Naranja):** Detección de Tarjetas SD.
2.  **Ingesta (Azul):** Transferencia segura a PC Local, o adopción de copias manuales.
3.  **Respaldo (Verde):** Clonación a Disco Externo.
4.  **Archivo Final (Púrpura):** Auditoría y transferencia a Servidor/NAS.

### Flujo de Trabajo
1.  **Columna 1:** Inserte la tarjeta SD. El sistema valida ID de hardware.
2.  **Columna 2:** "INICIAR COPIA". Ingesta verificada a repositorio local.
3.  **Columna 3:** Conecte disco externo (con archivo `.backup_drive`). "CLONAR".
4.  **Columna 4:** Seleccione ruta final (ej. `Z:\Proyecto`). "ARCHIVAR Y VALIDAR".
    -   El sistema verifica que los datos en `Z:\` coincidan exactamente con el `manifest.json` original y escribe un `audit_log.txt` como certificado.

> **Criterio para liberar una tarjeta:** la presencia de `audit_log.txt` con
> `Status: VERIFIED OK` en la carpeta de la sesión en el destino final. El
> diálogo de la interfaz no es evidencia suficiente.

### Nivel "Modo Puente" (Mejorado v3.1.2)
Se activa cuando el espacio en disco local es insuficiente. Permite la copia segura desde SD a Disco Externo utilizando el disco interno como búfer temporal volátil fragmentado.
**Seguridad Garantizada:** El sistema verifica recursivamente el tamaño del disco raíz y previene cuelgues del SO evaluando que ningún archivo individual sobrepase el espacio libre seguro.

### Salvaguardas y comportamientos a tener presentes
*   **Marcador obligatorio:** un disco externo solo se reconoce si tiene `.backup_drive` en su raíz. Evita clonar al disco equivocado.
*   **Detección única:** si hay varios discos con marcador, se elige el de letra alfabéticamente menor. Use "Elegir destino..." para forzar otro.
*   **Origen distinto de destino:** archivar una carpeta sobre sí misma se bloquea, porque `secure_copy` trunca el archivo de destino antes de leer el origen.
*   **Sin sobrescritura:** el respaldo a externo omite las carpetas de sesión que ya existan en el destino (no las completa). Una copia interrumpida debe eliminarse o renombrarse antes de reintentar.
*   **Colisión de nombres de sesión:** al archivar, si el destino ya tiene una sesión distinta con el mismo nombre, la nueva se guarda con sufijo de fecha y se reporta el conflicto.

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

Estados posibles por sesión: `adopted`, `verified`, `drift`, `error`,
`loose_files`, `empty`, `protected`, `no_manifest`, `cancelled`.
Códigos de salida: `0` sin observaciones, `1` hay desvíos o errores, `2` no se
pudo iniciar.

### Cadena de custodia parcial

Una copia hecha fuera del sistema **no puede** certificarse como bit-exacta respecto de la tarjeta original. Por honestidad forense, la adopción es explícita al respecto:

| | Ingesta desde SD | Copia adoptada |
|---|---|---|
| `origin` | `sd_ingest` | `manual_adopted` |
| `chain_of_custody` | `full` | `partial` |
| `hardware_id` | serial WMI | `null` |
| `audit_log.txt` | "Verified against original manifest hashes" | "Verificado contra línea base adoptada" + advertencia |

La adopción es **idempotente**: si la sesión ya tiene manifiesto adoptado, la segunda pasada solo verifica y reporta archivos modificados, faltantes o nuevos. Un manifiesto generado por una ingesta real desde SD **nunca** se sobrescribe, ni con `--force`.

### Límites de la adopción

*   **No es recursiva:** solo considera el primer nivel de subcarpetas. Una estructura `Sitio\Unidad\Pieza` requiere adoptar cada nivel intermedio.
*   **Archivos sueltos en la raíz** quedan fuera en modo por-subcarpeta; se reportan como `loose_files`.
*   **`hashes_blake3.json` aplana las claves a basename** por contrato con `fotogrametria-pipeline`, de modo que nombres repetidos dentro de una misma sesión colisionan y solo sobrevive el último hash. El `manifest.json` conserva las rutas completas y el sistema advierte del caso.

## 📂 Estructura del Proyecto

```text
/
├── src/                 # Código fuente principal
│   ├── lib_hardware.py  # Lógica WMI y detección de discos
│   ├── lib_copy.py      # Motor de copia segura y hashing con BLAKE3
│   ├── lib_storage.py   # Gestión de rutas, espacio y normalización de raíces
│   ├── lib_bridge.py    # Modo puente SD -> Interno -> Externo
│   ├── lib_archive.py   # Módulo de archivo final con auditoría
│   ├── lib_adopt.py     # Adopción de copias manuales (ingreso por etapa)
│   └── main.py          # Interfaz gráfica (CustomTkinter)
├── docs/                # Documentación operativa (para quien usa el sistema)
│   ├── GUIA_PRIMEROS_PASOS.md
│   └── CHECKLIST_TERRENO.md
├── scripts/             # Utilidades de operación y recuperación
│   └── adopt.py         # CLI de adopción sin interfaz gráfica
├── tests/               # Suite de pruebas unitarias (pytest)
├── knowledge/           # Base de conocimientos y decisiones técnicas
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

> En entornos sin terminal interactiva (CI, agentes), use
> `uv run cz commit -m "feat: descripción"` o `git commit` con el formato
> convencional; el prompt interactivo bloquea la ejecución.

### Releases Automáticos
Para generar una nueva versión distribuible:
1.  Actualice la versión en `pyproject.toml`.
2.  Cree un tag en git: `git tag v3.2.0` (debe coincidir con la versión).
3.  Empuje el tag: `git push origin v3.2.0`.
4.  GitHub Actions generará automáticamente el ejecutable `BackupCamera_v3.2.0.exe` y lo publicará en la sección **Releases**.

## ✍️ Autores

*   **Laboratorio de Arqueología Digital UC** - *Desarrollo Inicial*
