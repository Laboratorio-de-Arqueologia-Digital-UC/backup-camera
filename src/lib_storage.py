import os
import logging
import datetime
import json


def normalize_root(path):
    r"""
    Normaliza una raiz de almacenamiento para que sea absoluta.

    En Windows una ruta como "E:" es RELATIVA al directorio actual de esa
    unidad, no a su raiz. Por eso os.path.join("E:", "x") devuelve "E:x",
    que puede resolver a una carpeta inesperada. MonitorThread entrega los
    discos en ese formato ("%s:" % letra), asi que hay que corregirlo antes
    de construir cualquier ruta derivada.

    Devuelve el valor sin cambios si es None/vacio o si no es una unidad sola.
    """
    if not path:
        return path

    drive, tail = os.path.splitdrive(path)
    if drive and not tail:
        return drive + os.sep
    return path


def calculate_required_space(source_path):
    """
    Recursively sums file sizes in source_path.
    """
    total_size = 0
    for dirpath, _, filenames in os.walk(source_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total_size += os.path.getsize(fp)
    return total_size


def check_destination_space(dst_path_root, required_bytes):
    """
    Checks if destination has required_bytes + 1GB buffer.
    dst_path_root should be the drive root or valid path.
    """
    try:
        # Get statistics for the drive containing dst_path_root
        # In Windows, shutil.disk_usage works on folders too
        import shutil

        total, used, free = shutil.disk_usage(normalize_root(dst_path_root))

        buffer_bytes = 1 * 1024 * 1024 * 1024  # 1GB
        return free > (required_bytes + buffer_bytes)
    except Exception as e:
        logging.error(f"Error checking disk space: {e}")
        return False


def generate_folder_name(serial, base_path):
    """
    Generates folder name: YYYY-MM-DD_SD-Serial_HHMM
    If folder exists or manifest says we processed this card today,
    handle duplication logic.
    """
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M")

    # Sanitize serial for potential invalid chars in filenames
    safe_serial = "".join(c for c in serial if c.isalnum() or c in ("-", "_"))

    folder_name = f"{date_str}_SD-{safe_serial}_{time_str}"

    # Check for duplicate names (extremely simple logic per docs: "If user accepts, create new with updated time")
    # This naming convention practically guarantees uniqueness unless 2 ingests happen in same minute.
    # We can rely on the time suffix to provide uniqueness.

    return folder_name


def check_duplicate_ingest(repo_root, serial):
    """
    Scans repo_root to see if this serial was already ingested today.
    Returns: bool (True if duplicate found), str (Path of previous ingest if found)
    """
    now = datetime.datetime.now()
    date_prefix = now.strftime("%Y-%m-%d")
    target_pattern = f"{date_prefix}_SD-{serial}"

    if not os.path.exists(repo_root):
        return False, None

    for item in os.listdir(repo_root):
        if item.startswith(target_pattern) and os.path.isdir(
            os.path.join(repo_root, item)
        ):
            return True, os.path.join(repo_root, item)

    return False, None


def save_hashes_blake3(session_path, files):
    """
    Saves a flat JSON dictionary of {filename: hash} to hashes_blake3.json.
    Used by subsequent stage (fotogrametria-pipeline).

    NOTE: las claves son basename, no la ruta relativa. Es un contrato
    deliberado con fotogrametria-pipeline (ver tests/test_hashes.py), pero
    implica que dos archivos con el mismo nombre en subcarpetas distintas
    colisionan y solo sobrevive el ultimo. lib_adopt detecta y reporta ese
    caso; el manifest.json conserva siempre la ruta relativa completa.
    """
    hashes = {}
    for f in files:
        name = os.path.basename(f["path"])
        hashes[name] = f["hash"]

    output_path = os.path.join(session_path, "hashes_blake3.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(hashes, f, indent=4)
    return output_path
