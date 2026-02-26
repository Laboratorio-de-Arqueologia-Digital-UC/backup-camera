import os
import json
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def generate_hashes_for_session(session_path):
    """
    Reads manifest.json and generates hashes_blake3.json in the same folder.
    """
    session_path = Path(session_path)
    manifest_path = session_path / "manifest.json"
    hashes_path = session_path / "hashes_blake3.json"

    if not manifest_path.exists():
        return False, "No manifest.json found"

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        files = data.get("files", [])
        if not files:
            return False, "Manifest contains no files"

        # Generate flat hash map {basename: hash}
        hashes = {}
        for f in files:
            rel_path = f.get("path")
            file_hash = f.get("hash")
            if rel_path and file_hash:
                name = os.path.basename(rel_path)
                hashes[name] = file_hash

        with open(hashes_path, "w", encoding="utf-8") as f:
            json.dump(hashes, f, indent=4)

        return True, f"Generated {len(hashes)} hashes"

    except Exception as e:
        return False, str(e)


def scan_and_fix(root_dir):
    """
    Recursively finds session folders (any folder with manifest.json)
    and generates hashes_blake3.json if missing.
    """
    root_dir = Path(root_dir)
    logger.info(f"Scanning {root_dir} for session folders...")

    found_count = 0
    fixed_count = 0

    for root, dirs, files in os.walk(root_dir):
        if "manifest.json" in files:
            found_count += 1
            session_path = Path(root)
            hashes_path = session_path / "hashes_blake3.json"

            if not hashes_path.exists():
                success, msg = generate_hashes_for_session(session_path)
                if success:
                    logger.info(f"✅ [{session_path.name}] {msg}")
                    fixed_count += 1
                else:
                    logger.error(f"❌ [{session_path.name}] {msg}")
            else:
                logger.debug(f"ℹ️ [{session_path.name}] Already has hashes_blake3.json")

    logger.info("--- Summary ---")
    logger.info(f"Sessions found: {found_count}")
    logger.info(f"Hashes generated: {fixed_count}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate hashes_blake3.json from existing manifest.json files."
    )
    parser.add_argument(
        "directory",
        help="Root directory to scan (e.g., C:\\Backup_Ingesta or E:\\Backup_Ingesta)",
    )
    args = parser.parse_args()

    if os.path.exists(args.directory):
        scan_and_fix(args.directory)
    else:
        logger.error(f"Directory not found: {args.directory}")
