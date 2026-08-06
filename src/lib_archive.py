import os
import json
import time
import logging
import threading

from lib_copy import secure_copy
from lib_storage import normalize_root, save_hashes_blake3

SESSIONS_FOLDER = "Backup_Ingesta"
MANIFEST_NAME = "manifest.json"
AUDIT_NAME = "audit_log.txt"
ORIGIN_MANUAL = "manual_adopted"


def same_path(first, second):
    """Compara rutas de forma segura en sistemas insensibles a mayusculas."""
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(
        os.path.abspath(second)
    )


class ArchiveWorker(threading.Thread):
    def __init__(self, src_root, dest_root, app, sessions_root=None):
        r"""
        Worker to archive data from a source repository to Final Storage.

        Args:
            src_root (str): Origen. Puede ser la raiz de un disco externo (con
                            carpeta "Backup_Ingesta"), una carpeta que contenga
                            sesiones con manifiesto (copias adoptadas), o una
                            sesion individual.
            dest_root (str): Root of Final Storage (e.g., Z:\Archive).
            app: Reference to main GUI for updates.
            sessions_root (str): Opcional, fuerza la carpeta contenedora de
                            sesiones para permitir entrar al flujo en etapa 4.
        """
        super().__init__()
        # "E:" es relativa al directorio actual de esa unidad; "E:\" no.
        self.src_root = normalize_root(src_root)
        self.dest_root = normalize_root(dest_root)
        self.sessions_root = normalize_root(sessions_root)
        self.app = app
        self.daemon = True
        self.stop_event = threading.Event()

    # --- Resolucion flexible del origen ---------------------------------

    @staticmethod
    def _has_manifest(path):
        return os.path.exists(os.path.join(path, MANIFEST_NAME))

    @staticmethod
    def _subdirs(path):
        try:
            return [
                os.path.join(path, name)
                for name in sorted(os.listdir(path))
                if os.path.isdir(os.path.join(path, name))
            ]
        except OSError:
            return []

    def _collect_sessions(self):
        """
        Resuelve el contenedor de sesiones sin exigir una estructura unica.

        Devuelve (sesiones_con_manifiesto, omitidas_sin_manifiesto).
        """
        container = self.sessions_root

        if not container:
            nested = os.path.join(self.src_root, SESSIONS_FOLDER)
            if os.path.isdir(nested):
                container = nested
            elif os.path.basename(os.path.normpath(self.src_root)) == SESSIONS_FOLDER:
                container = self.src_root
            elif self._has_manifest(self.src_root):
                # Se apunto directamente a una sesion (por ejemplo adoptada).
                return [os.path.abspath(self.src_root)], []
            else:
                # Copia manual adoptada: las sesiones estan en la propia raiz.
                container = self.src_root

        subdirs = self._subdirs(container)
        sessions = [path for path in subdirs if self._has_manifest(path)]
        skipped = [path for path in subdirs if not self._has_manifest(path)]
        return sessions, skipped

    # --- Deteccion de colisiones en el destino --------------------------

    @staticmethod
    def _fingerprint(manifest_data):
        """Huella estable de una sesion: pares (ruta, hash) ordenados."""
        return sorted(
            (str(item.get("path")), str(item.get("hash")))
            for item in manifest_data.get("files", [])
        )

    def _resolve_destination(self, folder_name, manifest_data):
        """
        Devuelve (ruta_destino, ya_archivada, hubo_conflicto).

        La sola existencia de la carpeta destino ya no prueba que sea la misma
        sesion: los nombres adoptados ("Pieza_001") no son unicos como si lo
        eran los canonicos ("2026-08-06_SD-A1B2C3_1430"). Sin esta
        comparacion, una segunda sesion distinta con el mismo nombre se
        omitia y se contaba como archivada.
        """
        dest = os.path.join(self.dest_root, folder_name)
        audit = os.path.join(dest, AUDIT_NAME)

        if not (os.path.isdir(dest) and os.path.exists(audit)):
            return dest, False, False

        previous = None
        try:
            with open(
                os.path.join(dest, MANIFEST_NAME), "r", encoding="utf-8"
            ) as handle:
                previous = json.load(handle)
        except (OSError, ValueError):
            previous = None

        if previous is not None:
            if self._fingerprint(previous) == self._fingerprint(manifest_data):
                return dest, True, False

        stamp = time.strftime("%Y%m%d-%H%M%S")
        return os.path.join(self.dest_root, f"{folder_name}__{stamp}"), False, True

    # --- Auditoria ------------------------------------------------------

    @staticmethod
    def _write_audit_log(dest_session_path, src_session_path, manifest_data):
        """
        Escribe el audit_log.txt declarando el origen real de los datos.

        Una sesion adoptada fue copiada fuera del sistema, por lo que no se
        puede certificar equivalencia bit-exacta con la tarjeta SD: solo se
        certifica coincidencia con la linea base adoptada.
        """
        origin = manifest_data.get("origin", "legacy_unknown")
        chain = manifest_data.get("chain_of_custody")
        if not chain:
            chain = "partial" if origin == ORIGIN_MANUAL else "full"

        audit_log_path = os.path.join(dest_session_path, AUDIT_NAME)
        with open(audit_log_path, "w", encoding="utf-8") as audit:
            audit.write(f"Archive Timestamp: {time.ctime()}\n")
            audit.write(f"Source: {src_session_path}\n")
            audit.write("Status: VERIFIED OK\n")
            audit.write(f"Origin: {origin}\n")
            audit.write(f"Chain of custody: {chain}\n")

            if origin == ORIGIN_MANUAL:
                adopted_at = manifest_data.get("adopted_at", "?")
                adopted_by = manifest_data.get("adopted_by", "?")
                audit.write(
                    "Verificado contra linea base adoptada "
                    f"({adopted_at}, operador: {adopted_by}).\n"
                )
                audit.write(
                    "ADVERTENCIA: la copia previa se realizo fuera del sistema; "
                    "no se certifica equivalencia bit-exacta con la tarjeta SD "
                    "de origen.\n"
                )
            else:
                audit.write("Verified against original manifest hashes.\n")

    # --- Ejecucion ------------------------------------------------------

    def run(self):
        try:
            # secure_copy abre el destino con "wb", que TRUNCA el archivo a
            # cero bytes antes de leer el origen. Si ambos coinciden, el dato
            # original se destruye de forma irreversible.
            if same_path(self.src_root, self.dest_root):
                self.app.archive_failed(
                    "El origen y el destino final son la misma carpeta "
                    f"({self.src_root}). La operacion se cancelo para no "
                    "destruir los archivos originales."
                )
                return

            sessions, skipped = self._collect_sessions()

            if skipped:
                self.app.log_message(
                    f"AVISO: {len(skipped)} carpeta(s) sin {MANIFEST_NAME} fueron "
                    "omitidas. Adoptelas primero para incluirlas en el archivo."
                )
                for path in skipped:
                    logging.warning(f"Sin manifiesto, omitida: {path}")

            if not sessions:
                self.app.archive_failed(
                    "No se encontraron sesiones con manifiesto en el origen "
                    f"({self.src_root}). Si la copia se hizo manualmente, "
                    "genere primero la linea base de integridad (adopcion)."
                )
                return

            total_sessions = len(sessions)
            processed_count = 0
            conflicts = []

            self.app.update_archive_status(f"Escaneando {total_sessions} sesiones...")

            for src_session_path in sessions:
                if self.stop_event.is_set():
                    break

                folder_name = os.path.basename(os.path.normpath(src_session_path))
                manifest_path = os.path.join(src_session_path, MANIFEST_NAME)

                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest_data = json.load(f)
                except Exception as e:
                    logging.error(f"Error loading manifest for {folder_name}: {e}")
                    self.app.log_message(
                        f"ERROR: manifiesto ilegible en {folder_name} ({e}). "
                        "Sesion omitida."
                    )
                    continue

                dest_session_path, already_archived, conflict = (
                    self._resolve_destination(folder_name, manifest_data)
                )

                if already_archived:
                    logging.info(f"Skipping {folder_name}: Already archived.")
                    processed_count += 1
                    continue

                if conflict:
                    conflicts.append(folder_name)
                    self.app.log_message(
                        "CONFLICTO: ya existe una sesion archivada distinta "
                        f"llamada '{folder_name}'. Se archivara como "
                        f"'{os.path.basename(dest_session_path)}' para no "
                        "sobrescribir ni perder datos."
                    )

                # Segunda barrera: aunque las raices difieran, las rutas de
                # sesion pueden coincidir (src "E:\" + dest "E:\Backup_Ingesta").
                if same_path(src_session_path, dest_session_path):
                    self.app.log_message(
                        f"ERROR: la sesion '{folder_name}' tiene el mismo origen "
                        "y destino. Omitida para no destruir los archivos."
                    )
                    continue

                self.app.update_archive_status(f"Archivando: {folder_name}")

                files_to_copy = manifest_data.get("files", [])
                total_files = len(files_to_copy)

                os.makedirs(dest_session_path, exist_ok=True)

                session_valid = True

                for i, file_info in enumerate(files_to_copy):
                    if self.stop_event.is_set():
                        break

                    rel_path = file_info["path"]
                    original_hash = file_info["hash"]

                    src_file = os.path.join(src_session_path, rel_path)
                    dest_file = os.path.join(dest_session_path, rel_path)

                    progress_pct = i / total_files if total_files else 1.0
                    self.app.update_archive_progress(
                        progress_pct, f"Copiar+Audit: {rel_path}"
                    )

                    try:
                        # Hash nuevo calculado durante la copia
                        new_hash = secure_copy(src_file, dest_file)

                        # Verificacion contra el manifiesto de origen
                        if new_hash != original_hash:
                            err_msg = f"INTEGRITY ERROR: {rel_path} (Hash mismatch!)"
                            logging.error(err_msg)
                            self.app.log_message(f"CRITICAL: {err_msg}")
                            session_valid = False

                    except Exception as e:
                        logging.error(f"Copy error {rel_path}: {e}")
                        self.app.log_message(f"ERROR al copiar {rel_path}: {e}")
                        session_valid = False

                if session_valid:
                    secure_copy(
                        manifest_path,
                        os.path.join(dest_session_path, MANIFEST_NAME),
                    )
                    save_hashes_blake3(dest_session_path, files_to_copy)
                    self._write_audit_log(
                        dest_session_path, src_session_path, manifest_data
                    )
                    processed_count += 1
                else:
                    self.app.log_message(
                        f"ERROR: La sesion {folder_name} contiene errores de "
                        f"integridad. Copia parcial conservada en "
                        f"{dest_session_path} (sin audit_log) para revision."
                    )

            if conflicts:
                self.app.log_message(
                    f"AVISO: {len(conflicts)} sesion(es) con nombre duplicado en "
                    "el destino se archivaron con sufijo de fecha: "
                    + ", ".join(conflicts)
                )

            self.app.archive_complete(processed_count)

        except Exception as e:
            logging.error(f"Archive Fatal Error: {e}")
            self.app.archive_failed(str(e))

    def stop(self):
        self.stop_event.set()
