# Checklist de respaldo — versión para imprimir

> Resumen de una página. La explicación completa está en
> `docs/GUIA_PRIMEROS_PASOS.md`.

---

## Preparar un disco externo (una vez por disco)

1. Formatear: **NTFS** si es solo Windows, **exFAT** si también se usa en Mac.
2. Etiquetar el disco (`RESPALDO_LAD_01`) y rotularlo físicamente igual.
3. Crear el marcador en la **raíz** del disco (no dentro de una carpeta):
   ```
   type nul > E:\.backup_drive
   ```
4. Verificar: `dir E:\.backup_drive` debe listarlo.
5. Abrir el programa: el panel 3 debe mostrar el disco en verde.

**No conecte dos discos con marcador a la vez:** el programa toma el de letra
menor.

---

## Respaldo desde tarjeta

| Etapa | Acción | Qué confirmar |
|---|---|---|
| 1. Origen | Insertar tarjeta | Aparece el **ID Hardware** |
| 2. Ingesta | `INICIAR COPIA` | El resumen cuadra con lo esperado |
| 3. Respaldo | `CLONAR A EXTERNO` | Sin mensajes en rojo |
| 4. Archivo | `ARCHIVAR Y VALIDAR` | Se creó `audit_log.txt` |

Ejecutar el programa **como administrador**.

---

## Si las fotos ya se copiaron a mano

Panel 2 → **ADOPTAR CARPETA EXISTENTE** → elegir la carpeta → indicar si cada
subcarpeta es una pieza (**Sí**) o si todo es una sola sesión (**No**).

O por línea de comandos:

```bash
uv run python scripts/adopt.py --root "D:\Piezas" --mode per-piece \
    --operator "Su Nombre"
```

No mueve ni modifica archivos. La cadena de custodia queda **parcial**: adopte
cuanto antes, mientras la tarjeta original exista.

---

## REGLA DE ORO

> **No formatear la tarjeta hasta ver `audit_log.txt` con `VERIFIED OK` en la
> carpeta de la sesión en el servidor.**

Un diálogo en pantalla no es prueba. El archivo en el servidor sí.

---

## Verificación mensual

```bash
uv run python scripts/adopt.py --root "D:\Piezas" --verify
```

`verified` = bien · `drift` = revisar ya · `error` = archivo ilegible

---

## Nunca

- Formatear antes del certificado.
- Desconectar durante una copia.
- Renombrar o mover archivos de una sesión adoptada.
- Editar `manifest.json` a mano.
- Usar la misma carpeta como origen y destino.
- Ignorar un mensaje en rojo.

---

## Ante un error de integridad

**Detenerse. No formatear. Preguntar.**

Copiar el registro del recuadro negro inferior antes de cerrar el programa y
anotar: fecha, tarjeta, disco conectado y mensaje exacto.
