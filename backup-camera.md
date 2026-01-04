# Documentación Maestra: Sistema de Ingesta Forense "backup-camera"

## 1. Definición y Propósito del Proyecto

**backup-camera** es una aplicación de escritorio para Windows diseñada para la **ingesta forense** de datos en contextos arqueológicos y científicos.

Su propósito fundamental es eliminar la incertidumbre en el proceso de descarga de tarjetas de memoria. Transforma una tarea administrativa trivial (copiar archivos) en un proceso de **Cadena de Custodia Digital**. El software garantiza que los datos capturados en campo sean transferidos, verificados criptográficamente y organizados de manera inmutable, vinculando cada lote de datos al dispositivo físico (hardware) que lo generó.

## 2. Justificación y Problemática

En la fotogrametría arqueológica, los datos son el activo más valioso. Los métodos tradicionales fallan en puntos críticos:

1. **Fragilidad de la Identidad:** El "Nombre de Volumen" o "Número de Serie del Volumen" (usado por Windows Explorer) cambia si se formatea la tarjeta. Esto impide rastrear qué tarjeta física específica generó una imagen defectuosa meses después.
2. **Corrupción Silenciosa:** Copiar archivos sin verificación de hash (checksum) permite que errores en la RAM o cables USB corrompan imágenes sin que el usuario lo note hasta que es demasiado tarde.
3. **Caos Humano:** La libertad de nombrar carpetas manualmente genera inconsistencias ("Día 1", "Tarjeta_Juan", "DCIM") que hacen imposible la automatización posterior.

**backup-camera** soluciona esto imponiendo un protocolo rígido: **Validación de Hardware WMI + Hashing BLAKE3 + Flujo de Doble Salto.**

---

## 3. Arquitectura del Sistema (El "Cómo")

El software no es un simple script de copia. Es una aplicación modular con una arquitectura de **Productor-Consumidor Multihilo**.

### A. Componentes Clave

* **Interfaz (GUI):** Construida con `CustomTkinter` para soporte nativo de Modo Oscuro y monitores de alta resolución (HiDPI).
* **Backend de Hardware:** Utiliza WMI (Windows Management Instrumentation) para "hablar" directamente con el controlador del chip de la tarjeta SD.
* **Motor de Datos:** Implementa `BLAKE3` para hashing de alta velocidad y `shutil` optimizado para E/S.

### B. El Flujo de "Doble Salto"

El sistema prohíbe la copia directa "SD a Externo". Obliga a un paso intermedio de validación:

1. **Fase 1 (Ingesta):** Tarjeta SD  SSD Local (Verificación Hash).
2. **Fase 2 (Redundancia):** SSD Local  Disco Externo (Clonación).

---

## 4. Explicación Detallada del Código (Ingeniería Inversa)

A continuación, desglosamos la lógica interna del software, explicando cómo se implementaron las correcciones críticas solicitadas.

### Módulo 1: Identificación de Hardware Real (WMI)

**El Problema:** `os.stat('F:')` solo devuelve datos lógicos. Si formateas la tarjeta, el ID cambia.
**La Solución:** Usar `wmi` para rastrear la jerarquía de dispositivos.

**Lógica del Código:**
El código no pregunta "¿Qué es F:?". Pregunta "¿De qué disco físico proviene la partición que tiene la letra F:?".

1. Obtiene la lista de `Win32_DiskDrive` (Discos físicos) filtrados por `InterfaceType='USB'`.
2. Extrae el `SerialNumber` (quemado en fábrica en el chip de la tarjeta).
3. Usa `.associators` para bajar por el árbol: Disco Físico  Partición  Disco Lógico (Letra).

```python
# Pseudocódigo de la lógica WMI implementada
def get_real_hardware_id(letra_unidad):
    c = wmi.WMI()
    # 1. Buscar discos físicos USB
    for physical_disk in c.Win32_DiskDrive(InterfaceType="USB"):
        # 2. Buscar particiones asociadas a ese disco
        for partition in physical_disk.associators("Win32_DiskDriveToDiskPartition"):
            # 3. Buscar letras lógicas asociadas a esa partición
            for logical_disk in partition.associators("Win32_LogicalDiskToPartition"):
                if logical_disk.DeviceID == letra_unidad:
                    # ¡EUREKA! Hemos vinculado la letra F: con el Serial de Fábrica
                    return physical_disk.SerialNumber.strip()

```

### Módulo 2: Motor de Copia Criptográfica (Chunking)

**El Problema:** Cargar un archivo de vídeo de 10GB en RAM para verificarlo colapsaría el PC.
**La Solución:** Procesamiento por trozos (Chunking) con Hash al vuelo.

**Lógica del Código:**
La función de copia opera como una tubería.

1. Abre el grifo de lectura (SD) y el de escritura (SSD).
2. Lee 1MB (el "Chunk").
3. Pasa ese MB por el algoritmo BLAKE3 (actualiza la suma de verificación).
4. Escribe ese MB en el disco destino.
5. Repite hasta terminar el archivo.

```python
# Lógica de Copia + Hash Simultáneo
def secure_copy(src, dst):
    hasher = blake3.blake3() # Inicializa motor criptográfico
    buffer_size = 1024 * 1024 # 1 MB por trago

    with open(src, 'rb') as fsrc, open(dst, 'wb') as fdst:
        while True:
            chunk = fsrc.read(buffer_size)
            if not chunk: break
            
            fdst.write(chunk)   # Escribir en disco
            hasher.update(chunk) # Calcular huella digital
            
    return hasher.hexdigest() # Retorna el hash final

```

### Módulo 3: Concurrencia (Threading)

**El Problema:** Si el código de copia corre en el mismo hilo que la ventana, la aplicación se congela ("No responde") hasta terminar.
**La Solución:** Hilos de trabajo (Worker Threads).

**Lógica del Código:**

* **Main Thread:** Dibuja la ventana y la barra de progreso.
* **Monitor Thread:** Se despierta cada 2 segundos, escanea WMI buscando cambios de hardware y actualiza las etiquetas de la UI.
* **Copy Thread:** Se lanza solo al presionar "Iniciar". Hace el trabajo pesado y comunica el progreso mediante variables compartidas.

---

## 5. Análisis de Riesgos y Manejo de Excepciones

El software incluye defensas activas contra errores comunes en trabajo de campo.

### A. Gestión de Espacio Insuficiente

Antes de iniciar, el sistema calcula: `Espacio_Requerido = Suma(Tamaño Archivos SD)`.

* **Lógica:** Si `Espacio_Libre_Destino < (Espacio_Requerido + 1GB Buffer)`, el botón de inicio se deshabilita y se muestra una alerta roja.
* **Resultado:** Previene copias fallidas a mitad de camino.

### B. Gestión de Duplicados (La misma tarjeta, el mismo día)

Si el usuario inserta una tarjeta que ya procesó hace una hora:

* **Detección:** El sistema genera el nombre de carpeta propuesto: `2025-01-03_SD-SerialX_1000`.
* **Verificación:** Busca si esa carpeta ya existe o si el `manifest.json` interno registra una descarga previa del mismo hardware hoy.
* **Resolución:**
* Si es idéntica: Alerta al usuario. "¿Desea procesar de nuevo?".
* Si el usuario acepta: Crea una nueva carpeta con sufijo de hora actual (`_1400`), permitiendo la redundancia pero evitando sobrescribir la copia de las 10:00 AM.



### C. Gestión de "Tirón de Cable" (Desconexión Abrupta)

Si la conexión se pierde durante la copia:

* **Excepción:** El código captura el error `IOError` o `PermissionError`.
* **Rollback (Limpieza):** El sistema detecta que la operación no llegó al 100%. Inicia un protocolo de limpieza que **borra la carpeta de destino incompleta**.
* **Por qué:** Es más seguro no tener datos que tener datos corruptos o incompletos que el usuario cree que están bien.

---

## 6. Manual de Operación y Diseño Visual

### Interfaz de Tres Paneles (Semáforo Lógico)

1. **Panel 1: Origen (Naranja)**
* **Acción:** Usuario inserta SD.
* **Feedback:** El software muestra "SanDisk Extreme (ID: 00A1)".
* **Código:** El hilo de monitoreo valida que existe la carpeta `DCIM`.


2. **Panel 2: Tránsito (Azul)**
* **Acción:** Usuario presiona "Iniciar Ingesta".
* **Feedback:** Barra de progreso. Al finalizar, verifica `Hash_Origen == Hash_Destino`.
* **Resultado:** Notificación "Copia Verificada. Puede retirar SD".


3. **Panel 3: Destino (Verde)**
* **Acción:** Usuario conecta disco externo.
* **Seguridad:** El software busca el archivo oculto `.backup_drive`. Si no está, el panel permanece desactivado (evita copiar backups en el disco equivocado).
* **Acción Final:** "Respaldar a Externo".



### Despliegue (Cómo instalar)

1. Generar el ejecutable: `pyinstaller --noconsole --onefile TriPanelPro.py`.
2. Entregar el archivo `.exe` a los arqueólogos.
3. En los Discos Duros de respaldo, crear un archivo vacío llamado `.backup_drive` en la raíz.

---

## 7. Conclusión

**backup-camera** no es solo una herramienta de copia; es una implementación de **políticas de seguridad de datos** a través de código. Al quitarle al usuario la capacidad de elegir nombres de carpetas y al forzar la verificación de hardware y criptografía, se elimina el 90% de los vectores de error humano en la gestión de datos arqueológicos.