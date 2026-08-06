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
from lib_storage import save_hashes_blake3

MANIFEST_NAME = "manifest.json"
HASHES_NAME = "hashes_blake3.json"
AUDIT_NAME = "audit_log.txt"
MARKER_NAME = ".backup_drive"

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

PROBLEM_STATUSES = (STATUS_DRIFT, STATUS_PROTECTED, STATUS_NO_MANIFEST)

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


def scan_manual_folder(root, mode=MODE_PER_SUBFOLDER):
    """
    Detecta las sesiones candidatas dentro de una copia manual.

    mode="per_subfolder": cada subcarpeta de primer nivel es una sesion
                          (caso "carpeta ordenada por pieza").
    mode="single":        la carpeta raiz completa es una sola sesion.
    """
    root = os.path.abspath(root)
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
    root = os.path.abspath(root)
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
        "message": "",
    }
    base.update(extra)
    return base


def _warn_duplicate_basenames(session_path, entries):
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


def _build_entries(session_path, rel_paths, progress_cb=None):
    entries = []
    total_bytes = 0
    total = len(rel_paths)

    for index, rel_path in enumerate(rel_paths):
        full = os.path.join(session_path, rel_path)
        size = os.path.getsize(full)
        entries.append(
            {
                "path": rel_path,
                "hash": hash_file(full),
                "size": size,
                "mtime": int(os.path.getmtime(full)),
            }
        )
        total_bytes += size
        if progress_cb:
            progress_cb((index + 1) / total if total else 1.0, rel_path)

    return entries, total_bytes


def verify_session(session_path, progress_cb=None):
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
        if not os.path.exists(os.path.join(session_path, rel))
    ]

    checked = [rel for rel in present if rel in recorded]
    modified = []
    total = len(checked)

    for index, rel_path in enumerate(checked):
        actual = hash_file(os.path.join(session_path, rel_path))
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
            return verify_session(session_path, progress_cb)

    rel_paths = list_session_files(session_path)
    if not rel_paths:
        return _report(
            session_path,
            STATUS_EMPTY,
            message="La carpeta no contiene archivos de datos.",
        )

    entries, total_bytes = _build_entries(session_path, rel_paths, progress_cb)
    _warn_duplicate_basenames(session_path, entries)

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
):
    """Adopta (o verifica) todas las sesiones de una copia manual."""
    reports = []

    for session_path in scan_manual_folder(root, mode):
        if session_cb:
            session_cb(os.path.basename(os.path.normpath(session_path)))

        if verify_only:
            reports.append(verify_session(session_path, progress_cb))
        else:
            reports.append(
                adopt_session(
                    session_path,
                    operator=operator,
                    notes=notes,
                    entry_stage=entry_stage,
                    force=force,
                    progress_cb=progress_cb,
                )
            )

    return reports


def summarize(reports):
    """Resumen agregado de una corrida de adopcion o verificacion."""
    by_status: Dict[str, int] = {}
    has_problems = False

    for report in reports:
        status = report.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        if status in PROBLEM_STATUSES:
            has_problems = True

    summary: Dict[str, Any] = {
        "sessions": len(reports),
        "files": sum(report.get("files", 0) for report in reports),
        "bytes": sum(report.get("bytes", 0) for report in reports),
        "by_status": by_status,
        "has_problems": has_problems,
    }
    return summary


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
            )
            self._notify("adopt_complete", reports)
        except AdoptionError as exc:
            self._notify("adopt_failed", str(exc))
        except Exception as exc:
            logging.error(f"Adopt failed: {exc}")
            self._notify("adopt_failed", str(exc))
