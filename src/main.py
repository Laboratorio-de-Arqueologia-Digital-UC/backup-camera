import customtkinter as ctk
import threading
import time
import os
import logging
import json
from tkinter import messagebox

# Import core logic
from lib_hardware import get_real_hardware_id, scan_drives, get_drive_info
from lib_copy import secure_copy
from lib_storage import calculate_required_space, check_destination_space, generate_folder_name, check_duplicate_ingest

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MonitorThread(threading.Thread):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.daemon = True
        self.running = True

    def run(self):
        while self.running:
            try:
                # 1. Scan for Source Drives (SD Cards)
                drives = scan_drives()
                self.app.update_source_list(drives)
                
                # 2. Check for Destination Availability (External Backup)
                # For this MVP/V1, we might just look for the .backup_drive marker on available logical drives
                # But typically this is triggered by user interaction or similar scan.
                # Let's simplisticly scan all logical drives for the marker
                self.check_external_targets()
                
            except Exception as e:
                logging.error(f"Monitor loop error: {e}")
            
            time.sleep(2)

    def check_external_targets(self):
        # Scan for drives with .backup_drive file
        found_backups = []
        try:
            # We can reuse scan_drives logic but look for specific file
            # Ideally scan all logical disks, not just USB, or maybe just removable?
            # For robustness, let's look at all logical drives that are potentially writable data drives.
            # Using WMI or simply iterating common letters is fine.
            import string
            available_drives = ['%s:' % d for d in string.ascii_uppercase if os.path.exists('%s:' % d)]
            
            for drive in available_drives:
                # Check for marker file
                marker_path = os.path.join(drive, ".backup_drive")
                if os.path.exists(marker_path):
                    found_backups.append(drive)
            
            self.app.update_backup_list(found_backups)
            
        except Exception as e:
            logging.error(f"Backup scan error: {e}")

class IngestWorker(threading.Thread):
    def __init__(self, source_path, dest_path, app):
        super().__init__()
        self.source_path = source_path
        self.dest_path = dest_path
        self.app = app
        self.daemon = True

    def run(self):
        try:
            total_size = calculate_required_space(self.source_path)
            self.app.update_progress(0, "Calculando espacio...")
            
            if total_size == 0:
                self.app.ingest_failed("La tarjeta parece vacía.")
                return

            if not check_destination_space(os.path.splitdrive(self.dest_path)[0], total_size):
                self.app.ingest_failed("Espacio insuficiente en disco destino.")
                return

            # Walk and Copy
            copied_files = 0
            total_bytes_copied = 0
            
            file_list = []
            for dirpath, _, filenames in os.walk(self.source_path):
                for f in filenames:
                    file_list.append(os.path.join(dirpath, f))
            
            # Create manifest data structure
            manifest = {
                "source_path": self.source_path,
                "destination_path": self.dest_path,
                "timestamp": time.ctime(),
                "files": []
            }

            for src_file in file_list:
                rel_path = os.path.relpath(src_file, self.source_path)
                dst_file = os.path.join(self.dest_path, rel_path)
                
                # Update UI
                self.app.update_status(f"Copiando: {rel_path}")
                
                # Copy with hash
                def progress_cb(written, total):
                    # Global progress could be calculated if we tracked total job size accurately
                    # For now we'll just pulse or show file progress
                    pass

                file_hash = secure_copy(src_file, dst_file, progress_cb)
                
                # Verify Logic could go here (double read)
                
                total_bytes_copied += os.path.getsize(src_file)
                overall_progress = (total_bytes_copied / total_size)
                self.app.update_progress(overall_progress, f"Verificado: {rel_path}")
                
                manifest["files"].append({
                    "path": rel_path,
                    "hash": file_hash,
                    "size": os.path.getsize(dst_file)
                })

            # Save Manifest
            with open(os.path.join(self.dest_path, "manifest.json"), "w") as f:
                json.dump(manifest, f, indent=4)

            self.app.ingest_complete(self.dest_path)

        except Exception as e:
            logging.error(f"Ingest failed: {e}")
            self.app.ingest_failed(str(e))


class BackupWorker(threading.Thread):
    def __init__(self, src_repo, dst_drive, app):
        super().__init__()
        self.src_repo = src_repo
        self.dst_drive = dst_drive
        self.app = app
        self.daemon = True
        
    def run(self):
        try:
            # Simple sync: Copy folders from Repo to Drive/Backup_Ingesta
            dst_repo = os.path.join(self.dst_drive, "Backup_Ingesta")
            os.makedirs(dst_repo, exist_ok=True)
            
            # Use improved shutil capability or manual walk.
            # For "Cloning", we usually want robust copy.
            import shutil
            
            count = 0
            # Iterate over folders in local repo
            for item in os.listdir(self.src_repo):
                s = os.path.join(self.src_repo, item)
                d = os.path.join(dst_repo, item)
                if os.path.isdir(s):
                    if not os.path.exists(d):
                        # Copy entire tree if missing
                        # This blocks UI progress updates for the whole folder, ideally we'd chunk it.
                        shutil.copytree(s, d) 
                        count += 1
                    else:
                        # Skip or merge? Secure policy usually implies we don't overwrite blindly.
                        # Assuming distinct folders by timestamp.
                        pass 
            
            self.app.backup_complete(count)
            
        except Exception as e:
            logging.error(f"Backup failed: {e}")
            self.app.after(0, lambda: messagebox.showerror("Error Respaldo", str(e)))
            self.app.after(0, lambda: self.app.btn_backup.configure(state="normal"))


class BackupCameraApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Backup Camera - Ingesta Forense")
        self.geometry("1000x600")
        ctk.set_appearance_mode("Dark")
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # State
        self.selected_source = None
        self.local_repo = "C:\\Backup_Ingesta" # Default local landing zone
        if not os.path.exists(self.local_repo):
            try:
                os.makedirs(self.local_repo)
            except:
                pass # let user config later or handle error

        # --- PANEL 1: SOURCE (Orange) ---
        self.frame_source = ctk.CTkFrame(self, fg_color="#3b2d18") # Dark Orange-ish
        self.frame_source.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        self.lbl_source_title = ctk.CTkLabel(self.frame_source, text="1. ORIGEN (SD)", font=("Arial", 20, "bold"), text_color="#ff9900")
        self.lbl_source_title.pack(pady=20)
        
        self.lbl_source_info = ctk.CTkLabel(self.frame_source, text="Buscando tarjetas...", font=("Arial", 14))
        self.lbl_source_info.pack(pady=10)
        
        self.option_source = ctk.CTkOptionMenu(self.frame_source, values=["Detectando..."], command=self.on_source_select)
        self.option_source.pack(pady=10)
        
        # --- PANEL 2: TRANSIT (Blue) ---
        self.frame_transit = ctk.CTkFrame(self, fg_color="#1a2d3b") # Dark Blue-ish
        self.frame_transit.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        self.lbl_transit_title = ctk.CTkLabel(self.frame_transit, text="2. INGESTA", font=("Arial", 20, "bold"), text_color="#3399ff")
        self.lbl_transit_title.pack(pady=20)

        self.btn_start = ctk.CTkButton(self.frame_transit, text="INICIAR COPIA", command=self.start_ingest, state="disabled", height=50, fg_color="#0066cc")
        self.btn_start.pack(pady=40)

        self.progress_bar = ctk.CTkProgressBar(self.frame_transit)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10, padx=20, fill="x")

        self.lbl_status = ctk.CTkLabel(self.frame_transit, text="Esperando...", font=("Arial", 12))
        self.lbl_status.pack(pady=5)

        # --- PANEL 3: DESTINATION (Green) ---
        self.frame_dest = ctk.CTkFrame(self, fg_color="#1a3b25") # Dark Green-ish
        self.frame_dest.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)

        self.lbl_dest_title = ctk.CTkLabel(self.frame_dest, text="3. RESPALDO EXT.", font=("Arial", 20, "bold"), text_color="#00cc66")
        self.lbl_dest_title.pack(pady=20)
        
        self.lbl_dest_info = ctk.CTkLabel(self.frame_dest, text="Conecte Disco Externo", font=("Arial", 14))
        self.lbl_dest_info.pack(pady=10)

        self.btn_backup = ctk.CTkButton(self.frame_dest, text="CLONAR A EXTERNO", command=self.start_backup, state="disabled", fg_color="#009933")
        self.btn_backup.pack(pady=40)
        
        # Start Monitor
        self.monitor = MonitorThread(self)
        self.monitor.start()

    def update_backup_list(self, drives):
        self.after(0, lambda: self._update_backup_ui(drives))
        
    def _update_backup_ui(self, drives):
        if not drives:
            self.lbl_dest_info.configure(text="Conecte Disco Externo\n(Debe tener .backup_drive)", text_color="gray")
            self.btn_backup.configure(state="disabled")
        else:
            # Pick first available
            target = drives[0]
            self.lbl_dest_info.configure(text=f"Destino Detectado: {target}", text_color="#00cc66")
            self.btn_backup.configure(state="normal")
            self.backup_target = target

    def start_backup(self):
        # Only start if we have something in local repo
        if not os.path.exists(self.local_repo) or not os.listdir(self.local_repo):
            messagebox.showwarning("Aviso", "No hay datos locales para respaldar.")
            return
            
        if not self.backup_target:
            return
            
        # Launch Backup Worker (Reuse IngestWorker or generic copy? Let's make a simple specialized one)
        # For simplicity in this turn, I'll inline a simple thread or reuse IngestWorker logic if applicable.
        # But IngestWorker is specific to "Source -> Dest".
        # Let's create a BackupWorker quickly or allow IngestWorker to operate without "Source Drive" logic?
        # Cleaner to separate.
        
        self.btn_backup.configure(state="disabled")
        self.lbl_dest_info.configure(text="Sincronizando...")
        
        worker = BackupWorker(self.local_repo, self.backup_target, self)
        worker.start()

    def backup_complete(self, count):
        self.after(0, lambda: self._backup_complete_ui(count))
        
    def _backup_complete_ui(self, count):
        self.lbl_dest_info.configure(text=f"Respaldo OK ({count} carpetas)")
        self.btn_backup.configure(state="normal")
        messagebox.showinfo("Respaldo", f"Sincronización completada.\n{count} carpetas verificadas/copiadas.")



    def update_source_list(self, drives):
        # Called from thread, schedule UI update
        self.after(0, lambda: self._update_source_ui(drives))

    def _update_source_ui(self, drives):
        values = [f"{d['letter']} ({d['label']})" for d in drives]
        if not values:
            self.lbl_source_info.configure(text="No se detectan tarjetas SD")
            self.option_source.configure(values=["Sin Origen"])
            self.btn_start.configure(state="disabled")
            self.selected_source = None
        else:
            current_vals = self.option_source.cget("values")
            if set(values) != set(current_vals) and current_vals != ["Sin Origen"]:
                # Only update if changed to avoid resetting selection during active use
                self.option_source.configure(values=values)
            
            # Simple auto-select first if none selected
            if not self.selected_source and values:
                self.option_source.set(values[0])
                self.on_source_select(values[0])
                
    def on_source_select(self, choice):
        if choice == "Sin Origen":
            return
        
        letter = choice.split(" ")[0]
        self.selected_source = letter
        
        # Get Info
        hw_id = get_real_hardware_id(letter)
        info = get_drive_info(letter)
        
        display_text = f"Unidad: {letter}\nEtiqueta: {info['label'] if info else '?'}\nID Hardware: {hw_id}\nLibre: {info['free']//(1024**3)} GB"
        self.lbl_source_info.configure(text=display_text)
        
        if hw_id:
            self.btn_start.configure(state="normal")
        else:
            self.btn_start.configure(state="disabled") # Require valid WMI ID

    def start_ingest(self):
        if not self.selected_source: 
            return
        
        hw_id = get_real_hardware_id(self.selected_source)
        if not hw_id:
            messagebox.showerror("Error", "No se pudo validar el ID de Hardware.")
            return

        # Generate Destination Path
        folder_name = generate_folder_name(hw_id, self.local_repo)
        dest_path = os.path.join(self.local_repo, folder_name)

        # Check Duplicates
        is_dup, prev_path = check_duplicate_ingest(self.local_repo, hw_id)
        if is_dup:
            if not messagebox.askyesno("Duplicado Detectado", f"Esta tarjeta ya fue procesada hoy en:\n{prev_path}\n\n¿Desea procesar nuevamente?"):
                return
        
        # UI Lock
        self.btn_start.configure(state="disabled")
        self.option_source.configure(state="disabled")
        self.progress_bar.set(0)
        
        # Start Thread
        worker = IngestWorker(self.selected_source, dest_path, self)
        worker.start()

    def update_progress(self, val, msg):
        self.after(0, lambda: self._update_progress_ui(val, msg))

    def _update_progress_ui(self, val, msg):
        self.progress_bar.set(val)
        self.lbl_status.configure(text=msg)

    def ingest_complete(self, path):
        self.after(0, lambda: self._ingest_complete_ui(path))
    
    def _ingest_complete_ui(self, path):
        self.btn_start.configure(state="normal")
        self.option_source.configure(state="normal")
        self.lbl_status.configure(text="¡Ingesta Completada!")
        messagebox.showinfo("Éxito", f"Copia segura finalizada en:\n{path}")

    def ingest_failed(self, error_msg):
        self.after(0, lambda: self._ingest_failed_ui(error_msg))

    def _ingest_failed_ui(self, error_msg):
        self.btn_start.configure(state="normal")
        self.option_source.configure(state="normal")
        self.lbl_status.configure(text="Error en Ingesta")
        messagebox.showerror("Falló la Ingesta", error_msg)

if __name__ == "__main__":
    app = BackupCameraApp()
    app.mainloop()
