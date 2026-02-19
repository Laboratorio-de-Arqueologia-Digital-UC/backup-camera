import os
import json
import time
import logging
import threading
from tkinter import messagebox
from lib_copy import secure_copy, verify_hash

class ArchiveWorker(threading.Thread):
    def __init__(self, src_root, dest_root, app):
        """
        Worker to archive data from External Drive to Final Storage.
        
        Args:
            src_root (str): Root of the External Drive (e.g., E:\).
                            Expected to contain "Backup_Ingesta" folder.
            dest_root (str): Root of Final Storage (e.g., Z:\Archive).
            app: Reference to main GUI for updates.
        """
        super().__init__()
        self.src_root = src_root
        self.dest_root = dest_root
        self.app = app
        self.daemon = True
        self.stop_event = threading.Event()

    def run(self):
        try:
            # 1. Locate Source Content
            # We enforce a structure: src_root/Backup_Ingesta/<SessionFolders>
            # But the user might select just the drive letter.
            
            src_folder = os.path.join(self.src_root, "Backup_Ingesta")
            if not os.path.exists(src_folder):
                # Fallback: maybe they selected the folder directly?
                if os.path.basename(self.src_root) == "Backup_Ingesta":
                    src_folder = self.src_root
                else:
                    self.app.archive_failed("No se encontró la carpeta 'Backup_Ingesta' en el origen.")
                    return

            # 2. Iterate over session folders
            # We want to archive everything that hasn't been archived yet.
            # Realistically, for this V1, we iterate all and check if they exist in dest.
            
            session_folders = [f for f in os.listdir(src_folder) if os.path.isdir(os.path.join(src_folder, f))]
            if not session_folders:
                self.app.archive_failed("No hay carpetas de sesión en el respaldo externo.")
                return

            total_sessions = len(session_folders)
            processed_count = 0
            
            self.app.update_archive_status(f"Escaneando {total_sessions} sesiones...")

            for folder_name in session_folders:
                if self.stop_event.is_set():
                    break

                src_session_path = os.path.join(src_folder, folder_name)
                dest_session_path = os.path.join(self.dest_root, folder_name)

                # Check manifest presence
                manifest_path = os.path.join(src_session_path, "manifest.json")
                if not os.path.exists(manifest_path):
                    logging.warning(f"Skipping {folder_name}: No manifest.json found.")
                    continue

                # Load manifest for verification
                try:
                    with open(manifest_path, 'r') as f:
                        manifest_data = json.load(f)
                except Exception as e:
                    logging.error(f"Error loading manifest for {folder_name}: {e}")
                    continue

                self.app.update_archive_status(f"Archivando: {folder_name}")
                
                # Process Files in Session
                files_to_copy = manifest_data.get("files", [])
                total_files = len(files_to_copy)
                
                # Check if already archived (Simple check: folder exists and manifest exists)
                # In robust system, use audit log.
                if os.path.exists(dest_session_path) and os.path.exists(os.path.join(dest_session_path, "audit_log.txt")):
                     logging.info(f"Skipping {folder_name}: Already archived.")
                     processed_count += 1
                     continue

                os.makedirs(dest_session_path, exist_ok=True)
                
                session_valid = True
                
                for i, file_info in enumerate(files_to_copy):
                    if self.stop_event.is_set():
                        break
                        
                    rel_path = file_info['path']
                    original_hash = file_info['hash']
                    
                    src_file = os.path.join(src_session_path, rel_path)
                    dest_file = os.path.join(dest_session_path, rel_path)
                    
                    # Update Progress
                    progress_pct = (i / total_files) 
                    self.app.update_archive_progress(progress_pct, f"Copiar+Audit: {rel_path}")

                    # 1. Copy & Hash (Re-hashing on the fly)
                    try:
                        # We calculate NEW hash during copy
                        new_hash = secure_copy(src_file, dest_file)
                        
                        # 2. Verify against ORIGINAL manifest
                        if new_hash != original_hash:
                            err_msg = f"INTEGRITY ERROR: {rel_path} (Hash mismatch!)"
                            logging.error(err_msg)
                            self.app.log_message(f"CRITICAL: {err_msg}")
                            session_valid = False
                            # We don't stop strictly, but we flag the session.
                            # Optionally rename file to .corrupt
                        
                    except Exception as e:
                        logging.error(f"Copy error {rel_path}: {e}")
                        session_valid = False

                # 3. Finalize Session Archive
                if session_valid:
                    # Copy the manifest itself
                    secure_copy(manifest_path, os.path.join(dest_session_path, "manifest.json"))
                    
                    # Create Audit Log
                    audit_log_path = os.path.join(dest_session_path, "audit_log.txt")
                    with open(audit_log_path, "w") as audit:
                        audit.write(f"Archive Timestamp: {time.ctime()}\n")
                        audit.write(f"Source: {src_session_path}\n")
                        audit.write("Status: VERIFIED OK\n")
                        audit.write(f"Verified against original manifest hashes.\n")
                    
                    processed_count += 1
                else:
                    self.app.log_message(f"ERROR: La sesión {folder_name} contiene errores de integridad.")

            self.app.archive_complete(processed_count)

        except Exception as e:
            logging.error(f"Archive Fatal Error: {e}")
            self.app.archive_failed(str(e))

    def stop(self):
        self.stop_event.set()
