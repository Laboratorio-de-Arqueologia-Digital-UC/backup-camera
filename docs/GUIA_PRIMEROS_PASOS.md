# Guía de primeros pasos: respaldo seguro

> Para quien se incorpora al laboratorio y va a hacerse cargo del respaldo de
> material fotográfico. No asume conocimientos previos de informática forense.
> Tiempo de lectura: 20 minutos. Guarde esta guía a mano las primeras semanas.

**Qué cubre:** preparar el disco, respaldar desde la tarjeta, incorporar copias
que ya hizo a mano, comprobar que el respaldo está completo y qué hacer cuando
aparece un error.

**Qué NO cubre:** el procesamiento fotogramétrico posterior, el **traslado del
material terminado al almacenamiento institucional** (eso se hace por otra vía,
con otro procedimiento) y el desarrollo del programa (para eso está
`knowledge/knowledge.md`).

---

## 1. Por qué existe este flujo

Una excavación no se puede repetir. Si las fotos de una pieza se pierden o se
corrompen, no hay segunda oportunidad: el contexto ya fue desarmado. Por eso el
respaldo aquí no es "copiar y pegar", y descansa en tres ideas:

**Tres copias.** El dato vive en la tarjeta, en el computador, en un disco
externo y finalmente en el depósito final de la workstation. Nunca se elimina un
eslabón antes de confirmar el siguiente.

**Verificación, no confianza.** Copiar un archivo puede fallar en silencio: un
cable malo o un sector dañado producen un archivo que *parece* estar bien.
Para evitarlo, el programa calcula una **huella digital** (hash) de cada
archivo mientras lo copia y compara la huella del original con la de la copia.
Si difieren en un solo bit, avisa.

**Cadena de custodia.** Se registra de dónde vino cada archivo, cuándo y con
qué tarjeta física. Así, años después, se puede demostrar que la foto del
depósito es la misma que salió de la cámara.

> Si algo en esta guía le parece burocrático, recuerde: el objetivo es que en
> diez años alguien pueda confiar en estos archivos sin haber estado presente.

---

## 2. Glosario mínimo

| Término | Qué es |
|---|---|
| **Sesión** | Una carpeta con un conjunto de fotos y sus archivos de control. Es la unidad de trabajo del sistema. |
| **Hash (BLAKE3)** | Huella digital de un archivo: 64 caracteres. Si el archivo cambia aunque sea un bit, la huella cambia por completo. |
| **`manifest.json`** | El acta de la sesión: lista cada archivo con su hash, tamaño y origen. Es la fuente de verdad. |
| **`hashes_blake3.json`** | Lista simplificada de huellas que consume la etapa siguiente (fotogrametría). |
| **`audit_log.txt`** | Certificado que se crea en el depósito final cuando la sesión llegó y fue verificada. **Su presencia es la prueba de que el respaldo terminó.** |
| **`.backup_drive`** | Archivo marcador que usted crea en la raíz de un disco para autorizarlo como destino de respaldo. Sin él, el programa ignora el disco. |
| **Depósito final** | La carpeta de la workstation (o de almacenamiento conectado a ella) donde queda el material auditado. **No es el NAS:** el traslado al almacenamiento institucional se hace después, por otra vía. |
| **Adopción** | Generar el `manifest.json` de una copia que ya se hizo a mano, para que pueda entrar al flujo. |
| **Cadena de custodia parcial** | Marca de las copias adoptadas: se garantiza que no cambiaron desde la adopción, pero no que sean idénticas a la tarjeta original. |
| **Modo puente** | Modo para computadores con poco espacio: copia por trozos usando el disco interno como paso intermedio. |

---

## 3. Qué necesita antes de empezar

- **Windows 10 u 11.** El programa identifica el hardware con una tecnología
  propia de Windows (WMI); no funciona en macOS ni Linux.
- **Permisos de administrador.** Sin ellos, Windows a veces devuelve el número
  de serie de la tarjeta vacío y la etapa 1 no se habilita.
- **Un lector de tarjetas** (interno o USB).
- **Un disco externo** con capacidad de al menos 1,5 veces lo que espera
  respaldar en la temporada.
- **La ruta del depósito final** que use el laboratorio en la workstation.
- **El programa instalado**: pida el ejecutable `BackupCamera_vX.Y.Z.exe` o
  siga los pasos del `README.md` si va a ejecutarlo desde el código.

---

## 4. Preparar el disco externo (una sola vez por disco)

### 4.1 Elegir el formato

Si el disco se va a usar **solo en Windows**, formatéelo en **NTFS**. Si además
tiene que leerse en Mac, use **exFAT**, sabiendo que exFAT no lleva registro de
transacciones y es más frágil ante desconexiones bruscas: con exFAT, expulsar
el disco correctamente deja de ser un consejo y pasa a ser obligatorio.

### 4.2 Poner una etiqueta reconocible

En *Este equipo* → clic derecho sobre el disco → *Cambiar nombre*. Use algo
inequívoco: `RESPALDO_LAD_01`. Cuando haya tres discos sobre la mesa, la
etiqueta es lo que evita el error.

Escriba la misma etiqueta en el disco con un rotulador. Las letras de unidad
(`E:`, `F:`) cambian de un computador a otro; la etiqueta no.

### 4.3 Crear el marcador `.backup_drive`

Este archivo vacío es la salvaguarda central del sistema: **el programa no
escribirá en ningún disco que no lo tenga.** Así se evita clonar por accidente
sobre el disco personal de alguien.

La forma más simple es dejar que el programa lo cree: en el panel **3. RESPALDO
EXT.**, use *Elegir destino…*, seleccione el disco y responda **Sí** cuando
pregunte si desea crear el marcador.

Si prefiere hacerlo a mano, abra el *Símbolo del sistema* (`cmd`) y escriba,
reemplazando `E:` por la letra de su disco:

```
type nul > E:\.backup_drive
```

O en PowerShell:

```powershell
New-Item -Path "E:\.backup_drive" -ItemType File
```

No intente crearlo desde el Explorador escribiendo el nombre: Windows suele
rechazar los nombres que empiezan con punto, o le agrega `.txt` sin avisar
(y `.backup_drive.txt` **no** sirve).

**Verifique que quedó bien:**

```
dir E:\.backup_drive
```

Debe listar el archivo. Si dice *No se encuentra el archivo*, no se creó.

Dos detalles que importan:

- El marcador va en la **raíz** del disco (`E:\.backup_drive`), no dentro de
  una carpeta.
- **No conecte dos discos con marcador al mismo tiempo.** El programa elige
  automáticamente el de letra alfabéticamente menor, que puede no ser el que
  usted quiere. Si necesita hacerlo, fije el destino con *Elegir destino…*.

### 4.4 Comprobar que el programa lo reconoce

Abra el programa. El panel 3 debe pasar de *Conecte Disco Externo* a
**Destino Detectado: E:** en verde, con el espacio libre. Si sigue en gris,
revise el nombre del marcador.

---

## 5. Preparar el computador

1. Ejecute el programa **como administrador** (clic derecho → *Ejecutar como
   administrador*).
2. Revise la carpeta local del panel **2. INGESTA**. Por omisión es
   `C:\Backup_Ingesta`. Si el disco `C:` va justo de espacio, use *Cambiar
   Carpeta* y elija un disco interno con holgura.
3. Confirme el espacio libre que muestra el panel: necesita el tamaño de la
   tarjeta **más 1 GB** de margen, o la copia no arrancará.

---

## 6. El flujo normal, etapa por etapa

La ventana tiene cuatro columnas que se recorren de izquierda a derecha.

### Etapa 1 — Origen (naranja)

Inserte la tarjeta. En unos segundos aparecen la unidad, la etiqueta y el
**ID Hardware** (el número de serie físico). Ese ID es lo que ata los datos a
la tarjeta concreta.

*Si el ID sale vacío o dice `None`:* cierre el programa y ábralo como
administrador. Si persiste, el lector no expone el serial; use el modo de
adopción (sección 7) y anote la situación en la bitácora.

### Etapa 2 — Ingesta (azul)

Pulse **INICIAR COPIA**. El programa copia de la tarjeta a la carpeta local
calculando huellas al pasar, y crea una carpeta con nombre automático:

```
2026-08-06_SD-A1B2C3D4_1430
└── (sus fotos)
    manifest.json
    hashes_blake3.json
```

Si la tarjeta ya se procesó hoy, avisa antes de duplicar. Al terminar muestra
un resumen con la cantidad de archivos y el tamaño: **léalo**, es su primera
oportunidad de notar que faltan fotos.

### Etapa 3 — Respaldo externo (verde)

Con el disco conectado, pulse **CLONAR A EXTERNO**. Las sesiones se copian a
`E:\Backup_Ingesta\`.

Un detalle importante: si una carpeta de sesión **ya existe** en el disco, el
programa la **omite completa** en vez de completarla. Es una política
deliberada para no sobrescribir nada, pero significa que si una copia quedó a
medias por una desconexión, no se arregla sola. En ese caso renombre o elimine
la carpeta incompleta del disco externo y vuelva a clonar.

### Etapa 4 — Archivo final (morado)

1. Verifique el **Origen**: normalmente el disco externo. Con *Elegir origen…*
   puede archivar desde cualquier carpeta.
2. Indique la ruta del **depósito final** en la workstation.
3. Pulse **ARCHIVAR Y VALIDAR**.

Aquí ocurre lo esencial: cada archivo se copia al depósito y se le recalcula la
huella, que se compara contra el `manifest.json` original. Si todo coincide, se
escribe el `audit_log.txt`. Si algo no coincide, la sesión queda marcada y **no**
recibe certificado.

> **Fuera de alcance:** el traslado posterior de este material al
> almacenamiento institucional se hace por otra vía y con otro procedimiento.
> Este programa termina cuando el depósito final tiene su certificado.

> El origen y el destino no pueden ser la misma carpeta. Si lo son, el programa
> se detiene: copiar un archivo sobre sí mismo lo destruiría.

### El modo puente (opcional)

Si la tarjeta no cabe en el espacio libre del disco interno, use **MODO PUENTE**:
copia por trozos de unos 5 GB, verificando y liberando espacio a medida que
avanza, y siempre reserva 2 GB para que Windows no se ahogue. Requiere tarjeta
y disco externo conectados a la vez.

---

## 7. Si ya copió los archivos a mano (adopción)

Es una situación habitual y **no es un error**: alguien volvió de terreno y
copió las fotos al SSD arrastrándolas, ordenadas en una carpeta por pieza.

El problema es que esa copia no tiene huellas registradas, así que el sistema
no puede verificar nada. La **adopción** lo resuelve: recorre los archivos,
calcula sus huellas y escribe el `manifest.json` que falta. **No mueve, no
copia y no modifica ningún archivo**; solo agrega dos archivos de control por
carpeta.

### Desde el programa

1. Panel 2 → **ADOPTAR CARPETA EXISTENTE**.
2. Elija la carpeta raíz (por ejemplo `D:\Piezas`).
3. Responda cómo está organizada:
   - **Sí** → cada subcarpeta es una sesión independiente (caso "una carpeta
     por pieza"). Es lo más común.
   - **No** → toda la carpeta es una sola sesión.
4. Confirme. El proceso puede tardar: hay que leer cada archivo completo para
   calcular su huella. Puede detenerlo con **Cancelar** sin dejar nada a medias.

Al terminar, esa carpeta queda habilitada como origen de las etapas 3 y 4.

### Desde la línea de comandos

```bash
uv run python scripts/adopt.py --root "D:\Piezas" --mode per-piece \
    --operator "Nombre Apellido" --notes "Respaldo manual de terreno, marzo"
```

Use `--mode single` si toda la carpeta es una sola sesión.

El reporte incluye el **tiempo transcurrido y la velocidad**: con eso puede
estimar cuánto tardará una temporada completa antes de empezarla.

### Qué significa "cadena de custodia parcial"

Una copia hecha fuera del sistema **no se puede certificar** como idéntica a la
tarjeta: nadie verificó los bits en el momento de copiarlos. El sistema es
honesto al respecto y marca esas sesiones como `partial`. El certificado del
depósito final dirá que se verificaron contra la línea base adoptada, no contra
la SD.

Esto no invalida el material: significa que el punto de partida de la garantía
es la fecha de adopción. **Por eso conviene adoptar cuanto antes**, mientras la
tarjeta original todavía existe.

Una sesión que sí vino del flujo completo nunca se degrada a parcial: el
programa se niega a sobrescribir su manifiesto.

---

## 8. La regla de oro: cuándo puede formatear la tarjeta

**Solo cuando exista el `audit_log.txt` en el depósito final.**

Compruébelo usted mismo. Vaya a la carpeta de la sesión en el depósito y
verifique que estén los tres archivos:

```
<deposito_final>\2026-08-06_SD-A1B2C3D4_1430\
├── manifest.json
├── hashes_blake3.json
└── audit_log.txt      <-- este es el certificado
```

Ábralo: debe decir `Status: VERIFIED OK`. Un diálogo de "proceso completado" en
pantalla no es suficiente prueba; el archivo en el depósito sí lo es.

Si el mensaje dice *Sesiones procesadas: 0*, no se archivó nada. Revise la
sección 10.

---

## 9. Verificación periódica

Los discos se degradan en silencio. Una vez al mes, revise una parte del
material:

```bash
uv run python scripts/adopt.py --root "D:\Piezas" --verify
```

Esto no escribe nada: recalcula las huellas y las compara con el manifiesto.
Estados posibles:

| Estado | Significado | Qué hacer |
|---|---|---|
| `verified` | Todo coincide. | Nada. |
| `adopted` | Se acaba de crear la línea base. | Continuar a la etapa 3 o 4. |
| `drift` | Hay archivos modificados, faltantes o nuevos. | **Atención.** Vea abajo. |
| `error` | No se pudo leer un archivo. | Disco con problemas o archivo abierto en otro programa. |
| `loose_files` | Hay archivos sueltos en la raíz que quedarían fuera. | Muévalos a una subcarpeta. |
| `empty` | La carpeta no tiene archivos de datos. | Revisar si la copia falló. |
| `protected` | Es una sesión del flujo completo; no se re-genera. | Normal, no es un problema. |
| `no_manifest` | Nunca se adoptó. | Adoptarla. |

Sobre `drift`: si un archivo aparece como **modificado** y nadie lo editó a
propósito, sospeche del disco y compare con la copia del depósito de inmediato.
Si aparece como **nuevo**, probablemente alguien agregó fotos después de
adoptar; vuelva a adoptar con `--force` para incorporarlas a la línea base.

Códigos de salida del comando: `0` sin observaciones, `1` hay algo que revisar,
`2` no se pudo iniciar.

---

## 10. Mensajes de error y qué significan

| Mensaje | Causa | Solución |
|---|---|---|
| *No se detectan tarjetas SD* | Lector no reconocido o tarjeta mal insertada. | Reinsertar; probar otro lector. |
| `ID Hardware: None` | Windows no entrega el serial. | Ejecutar como administrador. |
| *Espacio insuficiente en disco destino* | Falta el tamaño de la tarjeta más 1 GB. | Liberar espacio o cambiar la carpeta local. |
| *Conecte Disco Externo (o use 'Elegir destino...')* | Falta el marcador `.backup_drive`. | Sección 4.3. |
| *No hay datos locales para respaldar* | La carpeta local está vacía. | Hacer primero la ingesta o apuntar a la carpeta correcta. |
| *No se encontraron sesiones con manifiesto en el origen* | Copia manual sin adoptar. | Adoptarla (sección 7). |
| *N carpeta(s) sin manifest.json fueron omitidas* | Parte del origen no está adoptado. | Aceptar la adopción que ofrece el programa. |
| *El origen y el destino final son la misma carpeta* | Se eligió la misma ruta dos veces. | Cambiar el destino. Este aviso le acaba de evitar perder archivos. |
| `CRITICAL: INTEGRITY ERROR ... (Hash mismatch!)` | La copia en el depósito no coincide con el original. | **No formatear nada.** Reintentar; si persiste, avisar al responsable: puede haber un disco o un cable fallando. |
| `CONFLICTO: ya existe una sesión archivada distinta llamada ...` | Dos sesiones distintas con el mismo nombre (por ejemplo dos `Pieza_001` de discos diferentes). | El programa guarda la segunda con la fecha añadida. Renómbrelas para que sean distinguibles. |
| *Un archivo supera el espacio interno libre seguro* | Un video muy grande no cabe en el búfer del modo puente. | Liberar espacio en `C:`. |

---

## 11. Lo que nunca debe hacer

- **Formatear la tarjeta** antes de ver el `audit_log.txt` en el depósito final.
- **Desconectar** un disco o sacar la tarjeta mientras hay una copia en curso.
- **Renombrar o mover** archivos dentro de una sesión ya adoptada: la
  verificación los reportará como faltantes y nuevos.
- **Editar a mano** el `manifest.json`. Es el acta; si algo no cuadra, se
  vuelve a adoptar.
- **Usar la misma carpeta** como origen y destino del archivo final.
- **Guardar una sola copia**, aunque sea en almacenamiento institucional.
  Todo almacenamiento falla.
- **Ignorar un mensaje en rojo** por tener prisa. Anótelo y pregunte.

---

## 12. Límites conocidos del sistema

Dicho de frente, para que no los descubra en el peor momento:

- **Solo Windows.**
- **El traslado al almacenamiento institucional no lo hace este programa.**
  Termina en el depósito final de la workstation.
- **La adopción no es recursiva.** Solo mira el primer nivel de subcarpetas. Si
  su estructura es `Sitio\Unidad\Pieza`, tendrá que adoptar cada nivel
  intermedio por separado.
- **Nombres de archivo repetidos colisionan** en `hashes_blake3.json`, porque
  ese archivo usa solo el nombre y no la ruta. Si `Pieza_001\IMG_0001.CR2` y
  `Pieza_002\IMG_0001.CR2` están en la *misma* sesión, la lista simplificada
  conserva una sola huella. El `manifest.json` conserva ambas y el programa
  avisa. Para evitarlo, adopte por pieza (cada pieza es una sesión aparte).
- **Archivos sueltos en la raíz** quedan fuera cuando se adopta por subcarpetas.
  El programa los reporta, pero no los incluye.
- **El respaldo a externo no completa carpetas existentes**, las omite.
- **La ingesta y el modo puente no se pueden cancelar** de forma segura una vez
  iniciados; la adopción y el archivo final sí.

---

## 13. Checklists

### Antes de salir a terreno
- [ ] Disco externo formateado, etiquetado y con `.backup_drive` verificado.
- [ ] Espacio libre suficiente en el disco externo y en el computador.
- [ ] Programa abierto una vez para confirmar que detecta el disco.
- [ ] Tarjetas formateadas **solo** después de confirmar que el material
      anterior ya tiene su certificado en el depósito final.

### Al volver de terreno (por cada tarjeta)
- [ ] Etapa 1: la tarjeta aparece con ID de hardware.
- [ ] Etapa 2: ingesta terminada; el resumen cuadra con lo que esperaba.
- [ ] Etapa 3: clonado al disco externo sin mensajes en rojo.
- [ ] Etapa 4: archivado al depósito final.
- [ ] `audit_log.txt` presente y con `VERIFIED OK`.
- [ ] Anotado en la bitácora: fecha, tarjeta, sesión, incidencias.
- [ ] Solo ahora: formatear la tarjeta.

### Si el material venía copiado a mano
- [ ] Adoptado lo antes posible, con su nombre como operador.
- [ ] Revisados los estados: nada en `drift`, `error` ni `loose_files`.
- [ ] Registrado en la bitácora que la cadena de custodia es **parcial**.
- [ ] Continuado con las etapas 3 y 4.

### Cada mes
- [ ] `--verify` sobre una parte del material.
- [ ] Revisada la salud de los discos (SMART).
- [ ] Confirmado que existen al menos dos copias de todo.

---

## 14. Cuando algo no cuadra

Si ve un error de integridad, un `drift` inesperado o cualquier cosa que no
entienda: **deténgase, no formatee nada y pregunte.** Un respaldo demorado se
arregla; un dato perdido, no.

Anote siempre qué hizo, qué decía el mensaje exacto y qué disco estaba
conectado. El recuadro negro inferior de la ventana lleva el registro de la
sesión: cópielo antes de cerrar el programa.

Dudas sobre el funcionamiento interno: `README.md` y `knowledge/knowledge.md`.
Problemas reproducibles: abra un issue en el repositorio (ver `SUPPORT.md`).
