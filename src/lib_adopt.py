"""
Adopcion de datos ya copiados: permite ingresar al flujo en cualquier etapa.

Caso de uso: el respaldo y la copia se hicieron manualmente hasta un SSD, con
una estructura propia ordenada por pieza. Este modulo genera la linea base de
integridad que el resto del pipeline espera (manifest.json y
hashes_blake3.json) SIN mover ni modificar los archivos originales.

Nota forense: un manifiesto adoptado no puede certificar equivalencia
bit-exacta con la tarjeta SD original, porque la copia ocurrio fuera del
sistema. Por eso se marca explicitamente con chain_of_custody="partial", y
lib_archive lo refleja en el audit_log.txt en lugar de afirmar que el archivo
es identico al que salio de la tarjeta.
"""

import datetime
import json
import logging
import os
import threading
from typing import Any, Dict

from lib_copy import hash_file
from lib_storage import normalize_root, save_hashes_blake3

MANIFEST_NAME = "manifest.json"
HASHES_NAME = "hashes_blake3.json"
AUDIT_NAME = "audit_log.txt"
MARKER_NAME = ".backup_drive"
SESSIONS_FOLDER = "Backup_Ingesta"

SCHEMA_VERSION = 2

ORIGIN_MANUAL = "manual_adopted"
ORIGIN_SD = "sd_ingest"
ORIGIN_LEGACY = "legacy_unknown"

CHAIN_FULL = "full"
CHAIN_PARTIAL = "partial"

MODE_PER_SUBFOLDER = "per_subfolder"
MODE_SINGLE = "single"

STATUS_ADOPTED = "adopted"
STATUS_VERIFIED = "verified"
STATUS_DRIFT = "drift"
STATUS_EMPTY = "empty"
STATUS_PROTECTED = "protected"
STATUS_NO_MANIFEST = "no_manifest"
STATUS_ERROR = "error"
STATUS_LOOSE = "loose_files"
STATUS_CANCELLED = "cancelled"

# Estados que comprometen la integridad de los datos. Son los unicos que
# exigen detener el trabajo, y los unicos que producen exit code 1 en el CLI.
PROBLEM_STATUSES = (
    STATUS_DRIFT,
    STATUS_PROTECTED,
    STATUS_NO_MANIFEST,
    STATUS_ERROR,
)

# Estados informativos sobre la carpeta raiz. NO son sesiones (contarlos como
# tales inflaria el recuento: 3 piezas + 1 aviso = "4 sesiones") y NO alteran
# el codigo de salida: un archivo suelto suele quedarse ahi de forma
# permanente, y una alarma que suena en cada verificacion deja de mirarse.
ADVISORY_STATUSES = (STATUS_LOOSE,)

# Archivos de control del propio sistema: nunca entran al manifiesto.
EXCLUDED_FILES = {
    MANIFEST_NAME.lower(),
    HASHES_NAME.lower(),
    AUDIT_NAME.lower(),
    MARKER_NAME.lower(),
    "thumbs.db",
    "desktop.ini",
    ".ds_store",
}


class AdoptionError(Exception):
    """Error de adopcion explicable al usuario."""


class AdoptionCancelled(Exception):
    """La operacion fue interrumpida a peticion del usuario."""


def scan_manual_folder(root, mode=MODE_PER_SUBFOLDER):
    """
    Detecta las sesiones candidatas dentro de una copia manual.

    mode="per_subfolder": cada subcarpeta de primer nivel es una sesion
                          (caso "carpeta ordenada por pieza").
    mode="single":        la carpeta raiz completa es una sola sesion.
    """
    root = os.path.abspath(normalize_root(root))
    if not os.path.isdir(root):
        raise AdoptionError(f"La ruta no existe o no es una carpeta: {root}")

    if mode == MODE_SINGLE:
        return [root]

    if mode != MODE_PER_SUBFOLDER:
        raise AdoptionError(f"Modo de adopcion no soportado: {mode}")

    sessions = [
        os.path.join(root, name)
        for name in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, name))
    ]
    if not sessions:
        raise AdoptionError(
            f"No se encontraron subcarpetas en {root}. "
            f"Use el modo '{MODE_SINGLE}' si la carpeta es una sola sesion."
        )
    return sessions


def list_session_files(session_path):
    """Rutas relativas ordenadas de los archivos de datos de la sesion."""
    collected = []
    for dirpath, _, filenames in os.walk(session_path):
        for name in filenames:
            if name.lower() in EXCLUDED_FILES:
                continue
            full = os.path.join(dirpath, name)
            collected.append(os.path.relpath(full, session_path))
    return sorted(collected)


def loose_files_at_root(root):
    """
    Archivos de datos sueltos en la raiz, que ninguna sesion cubriria.

    En modo por-pieza solo se adoptan subcarpetas, asi que un archivo dejado
    en la raiz quedaria permanentemente fuera del flujo sin ningun aviso.
    """
    root = os.path.abspath(normalize_root(root))
    try:
        names = os.listdir(root)
    except OSError:
        return []

    return sorted(
        name
        for name in names
        if os.path.isfile(os.path.join(root, name))
        and name.lower() not in EXCLUDED_FILES
    )


def read_manifest(session_path):
    """Lee el manifiesto de la sesion, o None si no existe."""
    path = os.path.join(session_path, MANIFEST_NAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise AdoptionError(f"Manifiesto ilegible en {session_path}: {exc}")


def manifest_origin(manifest):
    """Origen declarado (los manifiestos antiguos se tratan como legacy)."""
    if not manifest:
        return None
    return manifest.get("origin", ORIGIN_LEGACY)


def inspect_root(root):
    """
    Describe una carpeta para decidir si puede entrar al flujo.

    Devuelve un dict con:
      - "self": la raiz misma es una sesion con manifiesto.
      - "with_manifest": subcarpetas que ya tienen manifiesto.
      - "without_manifest": subcarpetas que requieren adopcion.
    """
    root = os.path.abspath(normalize_root(root))
    result: Dict[str, Any] = {
        "self": False,
        "with_manifest": [],
        "without_manifest": [],
    }

    if not os.path.isdir(root):
        return result

    result["self"] = os.path.exists(os.path.join(root, MANIFEST_NAME))

    try:
        names = sorted(os.listdir(root))
    except OSError:
        return result

    for name in names:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        if os.path.exists(os.path.join(path, MANIFEST_NAME)):
            result["with_manifest"].append(path)
        else:
            result["without_manifest"].append(path)

    return result


def pending_adoption(folder):
    """
    Subcarpetas que quedarian fuera del archivo final por falta de manifiesto.

    Centraliza la normalizacion de raices de unidad y la resolucion de
    "Backup_Ingesta", para que la GUI no tenga que replicar esa logica (y no
    vuelva a construir rutas relativas del tipo "E:Backup_Ingesta").
    """
    target = os.path.abspath(normalize_root(folder))
    nested = os.path.join(target, SESSIONS_FOLDER)
    if os.path.isdir(nested):
        target = nested

    state = inspect_root(target)
    if state["self"]:
        return []
    return list(state["without_manifest"])


def _report(session_path, status, **extra):
    base: Dict[str, Any] = {
        "session": session_path,
        "name": os.path.basename(os.path.normpath(session_path)),
        "status": status,
        "origin": None,
        "files": 0,
        "bytes": 0,
        "added": [],
        "missing": [],
        "modified": [],
        "loose": [],
        "duplicate_basenames": {},
        "message": "",
    }
    base.update(extra)
    return base


def _find_duplicate_basenames(session_path, entries):
    """
    hashes_blake3.json es plano (nombre -> hash) por compatibilidad con
    fotogrametria-pipeline. Si hay nombres repetidos en subcarpetas, solo
    sobrevive el ultimo de cada nombre: hay que advertirlo explicitamente.
    El manifest.json si conserva la ruta relativa completa.
    """
    seen: Dict[str, Any] = {}
    for entry in entries:
        seen.setdefault(os.path.basename(entry["path"]), []).append(entry["path"])

    duplicated = {name: paths for name, paths in seen.items() if len(paths) > 1}
    if duplicated:
        logging.warning(
            "%s: %d nombre(s) de archivo repetidos en subcarpetas; "
            "hashes_blake3.json conservara solo el ultimo de cada nombre.",
            session_path,
            len(duplicated),
        )
    return duplicated


def _build_entries(session_path, rel_paths, progress_cb=None, stop_event=None):
    entries = []
    total_bytes = 0
    total = len(rel_paths)

    for index, rel_path in enumerate(rel_paths):
        if stop_event is not None and stop_event.is_set():
            raise AdoptionCancelled(session_path)

        full = os.path.join(session_path, rel_path)
        try:
            size = os.path.getsize(full)
            digest = hash_file(full)
            mtime = int(os.path.getmtime(full))
        except OSError as exc:
            raise AdoptionError(f"No se pudo leer '{rel_path}': {exc}")

        entries.append(
            {
                "path": rel_path,
                "hash": digest,
                "size": size,
                "mtime": mtime,
            }
        )
        total_bytes += size
        if progress_cb:
            progress_cb((index + 1) / total if total else 1.0, rel_path)

    return entries, total_bytes


def verify_session(session_path, progress_cb=None, stop_event=None):
    """
    Re-hashea la sesion contra su manifiesto y reporta desvios.
    No escribe nada en disco.
    """
    session_path = os.path.abspath(session_path)
    manifest = read_manifest(session_path)
    if not manifest:
        return _report(
            session_path,
            STATUS_NO_MANIFEST,
            message=f"La sesion no tiene {MANIFEST_NAME}.",
        )

    recorded: Dict[str, Any] = {}
    for entry in manifest.get("files", []):
        if entry.get("path"):
            recorded[entry["path"]] = entry

    present = list_session_files(session_path)

    added = [rel for rel in present if rel not in recorded]
    missing = [
        rel
        for rel in sorted(recorded)
        if not os.path.isfile(os.path.join(session_path, rel))
    ]

    checked = [rel for rel in present if rel in recorded]
    modified = []
    total = len(checked)

    for index, rel_path in enumerate(checked):
        if stop_event is not None and stop_event.is_set():
            raise AdoptionCancelled(session_path)

        try:
            actual = hash_file(os.path.join(session_path, rel_path))
        except OSError as exc:
            raise AdoptionError(f"No se pudo leer '{rel_path}': {exc}")

        if actual != recorded[rel_path].get("hash"):
            modified.append(rel_path)
        if progress_cb:
            progress_cb((index + 1) / total if total else 1.0, rel_path)

    status = STATUS_DRIFT if (added or missing or modified) else STATUS_VERIFIED

    return _report(
        session_path,
        status,
        origin=manifest_origin(manifest),
        files=len(recorded),
        bytes=sum(int(entry.get("size") or 0) for entry in recorded.values()),
        added=added,
        missing=missing,
        modified=modified,
        manifest_path=os.path.join(session_path, MANIFEST_NAME),
    )


def adopt_session(
    session_path,
    operator=None,
    notes=None,
    entry_stage="local_ssd",
    force=False,
    progress_cb=None,
    stop_event=None,
):
    """
    Genera la linea base de integridad de una sesion ya copiada.

    - Si ya existe un manifiesto adoptado: verifica (no reescribe) salvo
      force=True.
    - Si el manifiesto proviene de una ingesta real desde SD: NUNCA lo
      sobrescribe, ni con force=True, porque degradaria una cadena de
      custodia completa a parcial.
    """
    session_path = os.path.abspath(session_path)
    if not os.path.isdir(session_path):
        raise AdoptionError(f"La sesion no existe: {session_path}")

    existing = read_manifest(session_path)
    if existing is not None:
        origin = manifest_origin(existing)
        if origin != ORIGIN_MANUAL:
            return _report(
                session_path,
                STATUS_PROTECTED,
                origin=origin,
                files=len(existing.get("files", [])),
                message=(
                    "Manifiesto protegido: fue generado por el flujo de ingesta "
                    f"(origin={origin}). No se re-genera la linea base para no "
                    "degradar la cadena de custodia. Verifique en su lugar."
                ),
            )
        if not force:
            return verify_session(session_path, progress_cb, stop_event)

    rel_paths = list_session_files(session_path)
    if not rel_paths:
        return _report(
            session_path,
            STATUS_EMPTY,
            message="La carpeta no contiene archivos de datos.",
        )

    entries, total_bytes = _build_entries(
        session_path, rel_paths, progress_cb, stop_event
    )
    duplicated = _find_duplicate_basenames(session_path, entries)

    now = datetime.datetime.now()
    manifest: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "origin": ORIGIN_MANUAL,
        "chain_of_custody": CHAIN_PARTIAL,
        "entry_stage": entry_stage,
        "hardware_id": None,
        "adopted_at": now.isoformat(timespec="seconds"),
        "adopted_by": operator or "desconocido",
        "notes": notes or "",
        # Claves compatibles con el pipeline existente (lib_archive, etc.)
        "source_path": session_path,
        "destination_path": session_path,
        "timestamp": now.ctime(),
        "files": entries,
    }

    manifest_path = os.path.join(session_path, MANIFEST_NAME)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=4, ensure_ascii=False)

    save_hashes_blake3(session_path, entries)

    return _report(
        session_path,
        STATUS_ADOPTED,
        origin=ORIGIN_MANUAL,
        files=len(entries),
        bytes=total_bytes,
        duplicate_basenames=duplicated,
        manifest_path=manifest_path,
    )


def adopt_root(
    root,
    mode=MODE_PER_SUBFOLDER,
    operator=None,
    notes=None,
    entry_stage="local_ssd",
    force=False,
    verify_only=False,
    progress_cb=None,
    session_cb=None,
    stop_event=None,
):
    """
    Adopta (o verifica) todas las sesiones de una copia manual.

    Cada sesion se aisla: un archivo ilegible (bloqueado, sin permisos o con
    sectores danados) no debe invalidar el trabajo de las demas.
    """
    reports = []

    if mode == MODE_PER_SUBFOLDER:
        loose = loose_files_at_root(root)
        if loose:
            reports.append(
                _report(
                    os.path.abspath(normalize_root(root)),
                    STATUS_LOOSE,
                    loose=loose,
                    message=(
                        f"{len(loose)} archivo(s) sueltos en la raiz no "
                        "pertenecen a ninguna pieza y quedarian fuera del "
                        "flujo. Muevalos a una subcarpeta o use el modo "
                        f"'{MODE_SINGLE}'."
                    ),
                )
            )

    for session_path in scan_manual_folder(root, mode):
        if stop_event is not None and stop_event.is_set():
            reports.append(
                _report(
                    session_path,
                    STATUS_CANCELLED,
                    message="Cancelado antes de procesar esta sesion.",
                )
            )
            break

        if session_cb:
            session_cb(os.path.basename(os.path.normpath(session_path)))

        try:
            if verify_only:
                report = verify_session(session_path, progress_cb, stop_event)
            else:
                report = adopt_session(
                    session_path,
                    operator=operator,
                    notes=notes,
                    entry_stage=entry_stage,
                    force=force,
                    progress_cb=progress_cb,
                    stop_event=stop_event,
                )
        except AdoptionCancelled:
            reports.append(
                _report(
                    session_path,
                    STATUS_CANCELLED,
                    message="Operacion cancelada por el usuario.",
                )
            )
            break
        except AdoptionError as exc:
            logging.error("Sesion con error: %s", exc)
            report = _report(session_path, STATUS_ERROR, message=str(exc))

        reports.append(report)

    return reports


def summarize(reports):
    """
    Resumen agregado de una corrida de adopcion o verificacion.

    Distingue dos niveles de severidad:
      - has_problems: hay un compromiso de integridad. Exige detener el
        trabajo y es lo unico que produce exit code 1.
      - has_advisories: hay observaciones sobre la organizacion de la carpeta
        (archivos sueltos). Se informan, pero no bloquean.

    Mezclar ambos niveles haria que la verificacion periodica alertara
    siempre, y una alarma permanente equivale a ninguna alarma.
    """
    by_status: Dict[str, int] = {}
    has_problems = False
    has_advisories = False
    sessions = 0
    advisories = 0

    for report in reports:
        status = report.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

        if status in ADVISORY_STATUSES:
            advisories += 1
            has_advisories = True
        else:
            sessions += 1

        if status in PROBLEM_STATUSES:
            has_problems = True

    summary: Dict[str, Any] = {
        "sessions": sessions,
        "advisories": advisories,
        "files": sum(report.get("files", 0) for report in reports),
        "bytes": sum(report.get("bytes", 0) for report in reports),
        "by_status": by_status,
        "has_problems": has_problems,
        "has_advisories": has_advisories,
    }
    return summary


def collect_advisories(reports):
    """Mensajes de los estados informativos, para mostrarlos aparte."""
    messages = []
    for report in reports:
        if report.get("status") in ADVISORY_STATUSES and report.get("message"):
            messages.append(report["message"])
    return messages


def collect_duplicate_warnings(reports):
    """Mensajes legibles sobre colisiones de nombre en hashes_blake3.json."""
    messages = []
    for report in reports:
        duplicated = report.get("duplicate_basenames") or {}
        if duplicated:
            messages.append(
                f"{report.get('name')}: {len(duplicated)} nombre(s) de archivo "
                "repetidos en subcarpetas; hashes_blake3.json conservara solo "
                "el ultimo de cada nombre (el manifest.json conserva todas "
                "las rutas)."
            )
    return messages


class AdoptWorker(threading.Thread):
    """
    Worker para la GUI, con la misma forma que IngestWorker y ArchiveWorker.

    Los callbacks se resuelven de forma tolerante para que el modulo siga
    siendo utilizable desde scripts sin interfaz.
    """

    def __init__(
        self,
        root,
        app,
        mode=MODE_PER_SUBFOLDER,
        operator=None,
        notes=None,
        entry_stage="local_ssd",
        force=False,
        verify_only=False,
    ):
        super().__init__()
        self.root = root
        self.app = app
        self.mode = mode
        self.operator = operator
        self.notes = notes
        self.entry_stage = entry_stage
        self.force = force
        self.verify_only = verify_only
        self.daemon = True
        self.stop_event = threading.Event()

    def _notify(self, handler_name, *args):
        handler = getattr(self.app, handler_name, None)
        if callable(handler):
            handler(*args)
        else:
            logging.info("[adopt] %s: %s", handler_name, args)

    def run(self):
        try:
            reports = adopt_root(
                self.root,
                mode=self.mode,
                operator=self.operator,
                notes=self.notes,
                entry_stage=self.entry_stage,
                force=self.force,
                verify_only=self.verify_only,
                progress_cb=lambda value, name: self._notify(
                    "update_adopt_progress", value, f"Hash: {name}"
                ),
                session_cb=lambda name: self._notify(
                    "update_adopt_status", f"Analizando: {name}"
                ),
                stop_event=self.stop_event,
            )

            for message in collect_advisories(reports):
                self._notify("log_message", f"AVISO: {message}")

            for message in collect_duplicate_warnings(reports):
                self._notify("log_message", f"AVISO: {message}")

            self._notify("adopt_complete", reports)
        except AdoptionError as exc:
            self._notify("adopt_failed", str(exc))
        except Exception as exc:
            logging.error(f"Adopt failed: {exc}")
            self._notify("adopt_failed", str(exc))

    def stop(self):
        self.stop_event.set()
