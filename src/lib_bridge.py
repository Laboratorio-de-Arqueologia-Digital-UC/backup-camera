import os
import shutil
import time
import json
import logging
import threading
from lib_copy import secure_copy
from lib_storage import save_hashes_blake3

# Reusing some logic from lib_storage if accessible, otherwise re-implementing/moving
# For now, minimal deps to keep it clean.


class BridgeWorker(threading.Thread):
    def __init__(self, source_path, internal_repo, external_path, app):
        super().__init__()
        self.source_path = source_path
        self.internal_repo = internal_repo
        self.external_path = external_path
        self.app = app
        self.daemon = True
        self.stop_signal = False

    def run(self):
        try:
            self.app.update_status("Calculando plan de copia...")

            # 1. Scan Source and Create Plan
            # We need a flat list of files to process
            file_list = []
            total_source_bytes = 0

            for dirpath, _, filenames in os.walk(self.source_path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    size = os.path.getsize(fp)
                    file_list.append(
                        {
                            "path": fp,
                            "rel_path": os.path.relpath(fp, self.source_path),
                            "size": size,
                        }
                    )
                    total_source_bytes += size

            if total_source_bytes == 0:
                self.app.ingest_failed("La tarjeta de origen parece vacía.")
                return

            # 2. Check External Space (Final Destination)
            try:
                # Require space for all data, check at the drive root to avoid FileNotFoundError
                ext_root = os.path.splitdrive(self.external_path)[0]
                ext_root = ext_root + "\\" if ext_root else self.external_path
                total_ext, used_ext, free_ext = shutil.disk_usage(ext_root)
                
                if free_ext < total_source_bytes:
                    self.app.ingest_failed(
                        f"Espacio insuficiente en Externo. Req: {total_source_bytes / 1024**3:.2f}GB"
                    )
                    return
            except Exception as e:
                logging.error(f"Error checking external space: {e}")
                self.app.ingest_failed("Error verificando disco externo.")
                return

            # 3. Determine Batch Size
            # Logic: If internal space allows, copy ALL at once (no chunking).
            # If not, use fixed chunks (e.g. 10GB) provided they fit.
            try:
                int_root = os.path.splitdrive(self.internal_repo)[0]
                int_root = int_root + "\\" if int_root else self.internal_repo
                total_int, used_int, free_int = shutil.disk_usage(int_root)

                # Safety buffer of 2GB to avoid choking OS
                safety_buffer = 2 * 1024**3
                available_for_bridge = free_int - safety_buffer

                if available_for_bridge <= 0:
                    self.app.ingest_failed(
                        "Espacio interno críticamente bajo. Libere espacio en C:."
                    )
                    return

                max_file_size = max(item["size"] for item in file_list)
                if max_file_size > available_for_bridge:
                    self.app.ingest_failed(
                        f"Un archivo ({max_file_size / 1024**3:.2f}GB) supera el espacio interno libre seguro para puente ({available_for_bridge / 1024**3:.2f}GB)."
                    )
                    return

                # Strategy Decision
                self.keep_internal = False  # Default

                if available_for_bridge >= total_source_bytes:
                    # Fits completely! One giant batch.
                    batch_limit_bytes = total_source_bytes
                    self.keep_internal = True
                    logging.info(
                        "Modo Puente: Espacio suficiente. Copia sin fragmentar y PERSISTENTE en disco interno."
                    )
                    self.app.update_status(
                        "Modo: Copia Persistente (No se borrará el interno)"
                    )
                else:
                    # Doesn't fit. Must chunk.
                    # Use a reasonable fixed size (e.g. 5GB) to ensure flow.
                    chunk_target = 5 * 1024**3  # 5 GB

                    # Ensure the chunk actually fits in available space
                    batch_limit_bytes = min(chunk_target, available_for_bridge)

                    # If calculated chunk is too small (<100MB), it's not worth it/risky
                    if batch_limit_bytes < 100 * 1024 * 1024:
                        self.app.ingest_failed(
                            f"Espacio interno insuficiente para operación segura ({available_for_bridge / 1024**2:.0f} MB libres)."
                        )
                        return

                    logging.info(
                        f"Modo Puente: Espacio limitado. Usando chunks de {batch_limit_bytes / 1024**3:.2f} GB (Volátil)."
                    )

            except Exception as e:
                logging.error(f"Error checking internal space: {e}")
                self.app.ingest_failed("Error verificando disco interno.")
                return

            # 4. Processing Loop
            manifest = {
                "source_path": self.source_path,
                "external_path": self.external_path,
                "timestamp": time.ctime(),
                "mode": "bridge-chunked",
                "files": [],
            }

            processed_bytes_total = 0

            # Create final target directory
            try:
                os.makedirs(self.external_path, exist_ok=True)
            except Exception as e:
                logging.error(f"Error al crear la ruta externa: {e}")
                self.app.ingest_failed("Error accediendo o creando ruta en disco externo.")
                return

            # Create a dedicated temp folder in internal repo to avoid clashes
            bridge_temp_dir = os.path.join(self.internal_repo, "_BRIDGE_TEMP")
            if os.path.exists(bridge_temp_dir):
                shutil.rmtree(bridge_temp_dir)  # Cleanup previous run if any
            os.makedirs(bridge_temp_dir)

            # Group files into batches
            current_batch = []
            current_batch_size = 0

            # Helper to process a batch
            def process_batch(batch_files):
                nonlocal processed_bytes_total

                # Step A: Copy SD -> Internal
                folder_map = []  # Store (src, int_path, ext_path, rel_path, size)

                for item in batch_files:
                    if self.stop_signal:
                        return False

                    src = item["path"]
                    rel = item["rel_path"]
                    size = item["size"]

                    # Internal Temp Path
                    int_path = os.path.join(bridge_temp_dir, rel)
                    # External Final Path
                    ext_path = os.path.join(self.external_path, rel)

                    self.app.update_status(f"Importando: {rel}")

                    # Copy SD -> Int
                    h_int = secure_copy(src, int_path)

                    folder_map.append(
                        {
                            "src": src,
                            "int": int_path,
                            "ext": ext_path,
                            "rel": rel,
                            "size": size,
                            "hash": h_int,
                        }
                    )

                # Step B: Copy Internal -> External
                for mapping in folder_map:
                    if self.stop_signal:
                        return False

                    self.app.update_status(f"Respaldando: {mapping['rel']}")

                    # Copy Int -> Ext
                    # We pass a progress callback that updates the global progress
                    # We estimate global progress: 50% for import, 50% for export per file?
                    # Simpler: Just count total bytes moved vs total*2 (since we move twice).

                    h_ext = secure_copy(mapping["int"], mapping["ext"])

                    if h_ext != mapping["hash"]:
                        raise IOError(f"Hash Mismatch en Puente! {mapping['rel']}")

                    manifest["files"].append(
                        {"path": mapping["rel"], "hash": h_ext, "size": mapping["size"]}
                    )

                    processed_bytes_total += mapping["size"]
                    # Visual feedback: We consider 'Done' when it hits external.
                    # Or we can do precise math. Let's send simple "Percent of Total Source Size Processed"
                    pct = processed_bytes_total / total_source_bytes
                    self.app.update_progress(pct, f"Seguro en Ext: {mapping['rel']}")

                # Step C: Delete Internal (Conditional)
                if not self.keep_internal:
                    for mapping in folder_map:
                        try:
                            if os.path.exists(mapping["int"]):
                                os.remove(mapping["int"])
                        except Exception:
                            pass
                else:
                    # If keeping, maybe we want to move them out of _BRIDGE_TEMP to a final location?
                    # Or essentially _BRIDGE_TEMP IS the location?
                    # For now, to adhere to logic, user likely wants them in the "Ingest Folder".
                    # But our logic put them in .internal_repo/_BRIDGE_TEMP/rel_path.
                    # We should probably move them to .internal_repo/FINAL_NAME?
                    # Or simply leave them there? The prompt says "no se borra".
                    # If we leave them in _BRIDGE_TEMP, they might get wiped next run.
                    # Let's effectively "Move" them to the standard ingest structure if keeping.
                    pass

                # Try to clean up empty dirs in temp
                # (Optional optimization)
                return True

            # Iterate and batch
            for item in file_list:
                if self.stop_signal:
                    break

                # Check if adding this file exceeds limit
                if (
                    current_batch_size + item["size"] > batch_limit_bytes
                ) and current_batch:
                    # Execute current batch
                    if not process_batch(current_batch):
                        raise Exception("Proceso detenido o fallido.")
                    current_batch = []
                    current_batch_size = 0

                current_batch.append(item)
                current_batch_size += item["size"]

            # Process final batch
            if current_batch and not self.stop_signal:
                if not process_batch(current_batch):
                    raise Exception("Proceso detenido.")

            # Cleanup Temp Dir structure
            # Only remove if we really wanted to delete everything.
            # If we are keeping internal, we should probably rename _BRIDGE_TEMP to a proper session name
            if self.keep_internal:
                try:
                    # Rename _BRIDGE_TEMP to match the session name in self.external_path
                    session_name = os.path.basename(self.external_path)
                    final_path = os.path.join(self.internal_repo, session_name)

                    if os.path.exists(final_path):
                        # If somehow it exists, add unique suffix
                        final_path += f"_{int(time.time())}"

                    if os.path.exists(bridge_temp_dir):
                        shutil.move(bridge_temp_dir, final_path)

                    self.app.update_status(
                        f"Copia interna guardada en: {os.path.basename(final_path)}"
                    )
                except Exception as e:
                    logging.error(f"Error renaming persisted bridge folder: {e}")
            else:
                try:
                    shutil.rmtree(bridge_temp_dir)
                except Exception:
                    pass

            # Save Manifest
            manifest_path = os.path.join(self.external_path, "manifest.json")
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=4)

            # Save flat hashes for subsequent pipeline
            save_hashes_blake3(self.external_path, manifest["files"])

            self.app.ingest_complete(self.external_path)

        except Exception as e:
            logging.error(f"Bridge Failed: {e}")
            self.app.ingest_failed(str(e))
