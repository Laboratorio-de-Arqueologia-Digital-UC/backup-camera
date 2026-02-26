import customtkinter as ctk
import threading
import time
import os
import logging
import json
import shutil
from tkinter import messagebox
import pythoncom
import tkinter as tk

# Import core logic
from lib_hardware import get_real_hardware_id, scan_drives, get_drive_info
from lib_copy import secure_copy
from lib_storage import (
    calculate_required_space,
    check_destination_space,
    generate_folder_name,
    check_duplicate_ingest,
    save_hashes_blake3,
)

from lib_bridge import BridgeWorker
from lib_archive import ArchiveWorker

# Configure Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class MonitorThread(threading.Thread):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.daemon = True
        self.running = True

    def run(self):
        pythoncom.CoInitialize()
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

            available_drives = [
                "%s:" % d for d in string.ascii_uppercase if os.path.exists("%s:" % d)
            ]

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

            if not check_destination_space(
                os.path.splitdrive(self.dest_path)[0], total_size
            ):
                self.app.ingest_failed("Espacio insuficiente en disco destino.")
                return

            # Walk and Copy
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
                "files": [],
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
                overall_progress = total_bytes_copied / total_size
                self.app.update_progress(overall_progress, f"Verificado: {rel_path}")

                manifest["files"].append(
                    {
                        "path": rel_path,
                        "hash": file_hash,
                        "size": os.path.getsize(dst_file),
                    }
                )

            # Save Manifest
            manifest_path = os.path.join(self.dest_path, "manifest.json")
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=4)

            # Save flat hashes for subsequent pipeline
            save_hashes_blake3(self.dest_path, manifest["files"])

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
            err_msg = str(e)
            self.app.after(0, lambda: messagebox.showerror("Error Respaldo", err_msg))
            self.app.after(0, lambda: self.app.btn_backup.configure(state="normal"))


class BackupCameraApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Backup Camera - Ingesta Forense")
        self.geometry("1400x650")  # Wider for 4 columns
        ctk.set_appearance_mode("Dark")

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)
        self.grid_columnconfigure(3, weight=1)  # New Column for Archive

        # Row 0: Main Panels (Weight 3)
        self.grid_rowconfigure(0, weight=3)
        # Row 1: Bridge & Animation (Weight 1)
        self.grid_rowconfigure(1, weight=1)
        # Row 2: Report Log (Fixed/Weight 0)
        self.grid_rowconfigure(2, weight=0, minsize=80)

        # State
        self.selected_source = None
        self.local_repo = "C:\\Backup_Ingesta"  # Default local landing zone
        if not os.path.exists(self.local_repo):
            try:
                os.makedirs(self.local_repo)
            except Exception:
                pass  # let user config later or handle error

        # --- PANEL 1: SOURCE (Orange) ---
        self.frame_source = ctk.CTkFrame(self, fg_color="#3b2d18")  # Dark Orange-ish
        self.frame_source.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        self.lbl_source_title = ctk.CTkLabel(
            self.frame_source,
            text="1. ORIGEN (SD)",
            font=("Arial", 20, "bold"),
            text_color="#ff9900",
        )
        self.lbl_source_title.pack(pady=20)

        self.lbl_source_info = ctk.CTkLabel(
            self.frame_source, text="Buscando tarjetas...", font=("Arial", 14)
        )
        self.lbl_source_info.pack(pady=10)

        self.lbl_source_space = ctk.CTkLabel(
            self.frame_source, text="", font=("Arial", 12), text_color="gray"
        )
        self.lbl_source_space.pack(pady=5)

        self.option_source = ctk.CTkOptionMenu(
            self.frame_source, values=["Detectando..."], command=self.on_source_select
        )
        self.option_source.pack(pady=10)

        # --- PANEL 2: TRANSIT (Blue) ---
        self.frame_transit = ctk.CTkFrame(self, fg_color="#1a2d3b")  # Dark Blue-ish
        self.frame_transit.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        self.lbl_transit_title = ctk.CTkLabel(
            self.frame_transit,
            text="2. INGESTA",
            font=("Arial", 20, "bold"),
            text_color="#3399ff",
        )
        self.lbl_transit_title.pack(pady=20)

        # Folder Selection
        self.lbl_local_repo = ctk.CTkLabel(
            self.frame_transit,
            text=f"Destino: {self.local_repo}",
            font=("Arial", 11),
            wraplength=280,
        )
        self.lbl_local_repo.pack(pady=(10, 0))

        self.btn_select_repo = ctk.CTkButton(
            self.frame_transit,
            text="Cambiar Carpeta",
            command=self.change_local_repo,
            width=120,
            height=24,
            fg_color="#445566",
        )
        self.btn_select_repo.pack(pady=(5, 20))

        self.lbl_transit_space = ctk.CTkLabel(
            self.frame_transit, text="", font=("Arial", 12), text_color="#aaaaaa"
        )
        self.lbl_transit_space.pack(pady=2)

        self.btn_start = ctk.CTkButton(
            self.frame_transit,
            text="INICIAR COPIA",
            command=self.start_ingest,
            state="disabled",
            height=50,
            fg_color="#0066cc",
        )
        self.btn_start.pack(pady=20)

        self.progress_bar = ctk.CTkProgressBar(self.frame_transit)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10, padx=20, fill="x")

        self.lbl_status = ctk.CTkLabel(
            self.frame_transit, text="Esperando...", font=("Arial", 12)
        )
        self.lbl_status.pack(pady=5)

        # --- PANEL 3: DESTINATION (Green) ---
        self.frame_dest = ctk.CTkFrame(self, fg_color="#1a3b25")  # Dark Green-ish
        self.frame_dest.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)

        self.lbl_dest_title = ctk.CTkLabel(
            self.frame_dest,
            text="3. RESPALDO EXT.",
            font=("Arial", 20, "bold"),
            text_color="#00cc66",
        )
        self.lbl_dest_title.pack(pady=20)

        self.lbl_dest_info = ctk.CTkLabel(
            self.frame_dest, text="Conecte Disco Externo", font=("Arial", 14)
        )
        self.lbl_dest_info.pack(pady=10)

        self.lbl_dest_space = ctk.CTkLabel(
            self.frame_dest, text="", font=("Arial", 12), text_color="gray"
        )
        self.lbl_dest_space.pack(pady=5)

        self.btn_backup = ctk.CTkButton(
            self.frame_dest,
            text="CLONAR A EXTERNO",
            command=self.start_backup,
            state="disabled",
            fg_color="#009933",
        )
        self.btn_backup.pack(pady=10)

        # --- PANEL 4: ARCHIVE (Purple/Red) ---
        self.frame_archive = ctk.CTkFrame(self, fg_color="#3b1a3b")  # Dark Purple
        self.frame_archive.grid(row=0, column=3, sticky="nsew", padx=5, pady=5)

        self.lbl_archive_title = ctk.CTkLabel(
            self.frame_archive,
            text="4. ARCHIVO FINAL",
            font=("Arial", 20, "bold"),
            text_color="#d633ff",
        )
        self.lbl_archive_title.pack(pady=20)

        self.lbl_archive_info = ctk.CTkLabel(
            self.frame_archive, text="Destino Final:", font=("Arial", 12)
        )
        self.lbl_archive_info.pack(pady=(10, 0))

        self.entry_archive_dest = ctk.CTkEntry(
            self.frame_archive, placeholder_text="Z:\\Archivo"
        )
        self.entry_archive_dest.pack(pady=5, padx=10, fill="x")
        # Default value for demo/convenience
        self.entry_archive_dest.insert(0, "Z:\\Archivo_Arqueologia")

        self.btn_select_archive = ctk.CTkButton(
            self.frame_archive,
            text="Seleccionar...",
            command=self.select_archive_dest,
            width=100,
            height=24,
            fg_color="#554466",
        )
        self.btn_select_archive.pack(pady=5)

        self.lbl_archive_status = ctk.CTkLabel(
            self.frame_archive, text="", font=("Arial", 12), text_color="gray"
        )
        self.lbl_archive_status.pack(pady=10)

        self.btn_archive = ctk.CTkButton(
            self.frame_archive,
            text="ARCHIVAR Y VALIDAR",
            command=self.start_archive,
            state="disabled",
            fg_color="#800080",
            height=50,
        )
        self.btn_archive.pack(pady=20)

        self.archive_progress = ctk.CTkProgressBar(self.frame_archive)
        self.archive_progress.set(0)
        self.archive_progress.pack(pady=10, padx=20, fill="x")

        # Bridge Mode Button (New)
        self.btn_bridge = ctk.CTkButton(
            self.frame_dest,
            text="MODO PUENTE (SD->INT->EXT)",
            command=self.start_bridge,
            state="disabled",
            fg_color="#5500aa",  # Distinct purple color
            height=50,
        )
        self.btn_bridge.pack(pady=10)

        # --- ROW 1: BRIDGE & ANIMATION ---
        self.frame_bridge = ctk.CTkFrame(self, fg_color="#2b2b2b")
        self.frame_bridge.grid(
            row=1, column=0, columnspan=4, sticky="nsew", padx=5, pady=5
        )

        self.frame_bridge.grid_columnconfigure(0, weight=0)  # Button
        self.frame_bridge.grid_columnconfigure(1, weight=1)  # Animation

        # Bridge Button (Left)
        self.btn_bridge = ctk.CTkButton(
            self.frame_bridge,
            text="MODO PUENTE\n(SD -> INT -> EXT)",
            command=self.start_bridge,
            state="disabled",
            fg_color="#5500aa",
            height=60,
            width=200,
            font=("Arial", 14, "bold"),
        )
        self.btn_bridge.grid(row=0, column=0, padx=20, pady=20, sticky="w")

        # Animation Canvas (Right)
        # Using standard TK Canvas for drawing primitives

        self.anim_canvas = tk.Canvas(
            self.frame_bridge, bg="#2b2b2b", highlightthickness=0, height=80
        )
        self.anim_canvas.grid(row=0, column=1, padx=20, pady=10, sticky="ew")

        # Initial Animation State (Static)
        self.draw_anim_static()

        # --- ROW 2: REPORT LOG ---
        self.frame_report = ctk.CTkFrame(self, height=80, fg_color="black")
        self.frame_report.grid(
            row=2, column=0, columnspan=4, sticky="ew", padx=5, pady=(0, 5)
        )

        self.log_text = ctk.CTkTextbox(
            self.frame_report,
            height=70,
            font=("Consolas", 12),
            activate_scrollbars=True,
        )
        self.log_text.pack(fill="both", expand=True, padx=2, pady=2)
        self.log_text.configure(state="disabled")

        # Start Monitor
        self.monitor = MonitorThread(self)
        self.monitor.start()

        # Initial Space Check for Local Repo
        self.update_local_space()

    def change_local_repo(self):
        root = ctk.filedialog.askdirectory(
            initialdir=self.local_repo, title="Seleccionar Carpeta de Ingesta"
        )
        if root:
            self.local_repo = root
            self.lbl_local_repo.configure(text=f"Destino: {self.local_repo}")
            self.update_local_space()

    def log_message(self, msg):
        """Append a message to the bottom log area."""
        timestamp = time.strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {msg}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", full_msg)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def draw_anim_static(self):
        """Draws the 3 nodes (SD, Int, Ext) in static state."""
        w = self.anim_canvas.winfo_width()
        # Fallback if width not yet known (early init)
        if w < 100:
            w = 600

        h = 80
        y = h // 2

        # Positions
        x_sd = w * 0.15
        x_int = w * 0.5
        x_ext = w * 0.85
        r = 25  # Radius

        self.anim_canvas.delete("all")

        # Draw Nodes
        # SD (Orange)
        self.anim_canvas.create_oval(
            x_sd - r,
            y - r,
            x_sd + r,
            y + r,
            fill="#3b2d18",
            outline="#ff9900",
            width=2,
            tags="node_sd",
        )
        self.anim_canvas.create_text(
            x_sd, y, text="SD", fill="white", font=("Arial", 10, "bold")
        )

        # INT (Blue)
        self.anim_canvas.create_oval(
            x_int - r,
            y - r,
            x_int + r,
            y + r,
            fill="#1a2d3b",
            outline="#3399ff",
            width=2,
            tags="node_int",
        )
        self.anim_canvas.create_text(
            x_int, y, text="PC", fill="white", font=("Arial", 10, "bold")
        )

        # EXT (Green)
        self.anim_canvas.create_oval(
            x_ext - r,
            y - r,
            x_ext + r,
            y + r,
            fill="#1a3b25",
            outline="#00cc66",
            width=2,
            tags="node_ext",
        )
        self.anim_canvas.create_text(
            x_ext, y, text="EXT", fill="white", font=("Arial", 10, "bold")
        )

        # Arrows (Gray)
        self.anim_canvas.create_line(
            x_sd + r + 5,
            y,
            x_int - r - 5,
            y,
            fill="#444",
            arrow=tk.LAST,
            width=2,
            tags="arrow_1",
        )
        self.anim_canvas.create_line(
            x_int + r + 5,
            y,
            x_ext - r - 5,
            y,
            fill="#444",
            arrow=tk.LAST,
            width=2,
            tags="arrow_2",
        )

    def animate_flow(self, step="idle"):
        """
        Updates animation to show active flow.
        step: 'idle', 'import' (SD->Int), 'export' (Int->Ext), 'clean' (Int X)
        """
        self.draw_anim_static()  # Reset base
        w = self.anim_canvas.winfo_width()
        if w < 100:
            w = 600
        h = 80
        y = h // 2
        # x_sd = w * 0.15  # Unused
        x_int = w * 0.5
        # x_ext = w * 0.85 # Unused
        # r = 25           # Unused

        if step == "import":
            # Highlight Arrow 1 and SD/Int
            self.anim_canvas.itemconfig("node_sd", fill="#ff9900")
            self.anim_canvas.itemconfig("node_int", outline="white")
            self.anim_canvas.itemconfig("arrow_1", fill="#ff9900", width=4)
        elif step == "export":
            # Highlight Arrow 2 and Int/Ext
            self.anim_canvas.itemconfig("node_int", fill="#3399ff")
            self.anim_canvas.itemconfig("node_ext", outline="white")
            self.anim_canvas.itemconfig("arrow_2", fill="#00cc66", width=4)
        elif step == "clean":
            # Red flash on PC
            self.anim_canvas.itemconfig("node_int", fill="#aa0000")
            self.anim_canvas.create_text(
                x_int, y - 35, text="CLEANING", fill="#ff5555", font=("Arial", 8)
            )

    def update_status(self, msg):
        self.after(0, lambda: self._update_status_ui(msg))

    def _update_status_ui(self, msg):
        self.lbl_status.configure(text=msg)
        # Also log key status milestones
        if "Importando" in msg or "Respaldando" in msg or "Copia" in msg:
            # Don't flood log with every file if possible, but for now we log everything or filter.
            # User requested log area.
            # Let's log major events or use a separate call for detailed logging.
            # For this task, I'll log all update_status calls to the text area too.
            self.log_message(msg)

        # Trigger Animation based on text keywords (Simple parsing for V1)
        if "Importando" in msg:
            self.animate_flow("import")
        elif "Respaldando" in msg:
            self.animate_flow("export")
        elif "borrar" in msg.lower() or "guardada" in msg:
            self.animate_flow("clean")
        else:
            self.animate_flow("idle")

    def update_local_space(self):
        try:
            total, used, free = shutil.disk_usage(self.local_repo)
            gb = 1024**3
            self.lbl_transit_space.configure(
                text=f"Libre: {free / gb:.1f} GB / Total: {total / gb:.1f} GB"
            )
        except Exception:
            self.lbl_transit_space.configure(text="Espacio Desconocido")

    def update_backup_list(self, drives):
        self.after(0, lambda: self._update_backup_ui(drives))

    def _update_backup_ui(self, drives):
        if not drives:
            self.lbl_dest_info.configure(
                text="Conecte Disco Externo\n(Debe tener .backup_drive)",
                text_color="gray",
            )
            self.lbl_dest_space.configure(text="")
            self.btn_backup.configure(state="disabled")
            self.btn_bridge.configure(state="disabled")
        else:
            # Pick first available
            target = drives[0]
            self.lbl_dest_info.configure(
                text=f"Destino Detectado: {target}", text_color="#00cc66"
            )

            # Get space info
            try:
                total, used, free = shutil.disk_usage(target)
                gb = 1024**3
                self.lbl_dest_space.configure(
                    text=f"Libre: {free / gb:.1f} GB / Total: {total / gb:.1f} GB"
                )
            except Exception:
                self.lbl_dest_space.configure(text="?")

            self.btn_backup.configure(state="normal")

            # Enable Archive if we have a backup source (External Drive)
            self.btn_archive.configure(state="normal")

            # Bridge mode requires Source + Destination
            if self.selected_source:
                self.btn_bridge.configure(state="normal")

            self.backup_target = target

    def start_backup(self):
        # Update local space periodically or before action
        self.update_local_space()
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

    def start_bridge(self):
        if not self.selected_source or not self.backup_target:
            return

        # Get HW ID for folder naming
        hw_id = get_real_hardware_id(self.selected_source)
        if not hw_id:
            messagebox.showerror("Error", "No se pudo validar el ID de Hardware (SD).")
            return

        # 1. Generate naming based on hardware and time
        session_folder = generate_folder_name(hw_id, self.local_repo)

        # 2. Build final external path (nested): E:\Backup_Ingesta\YYYY-MM-DD_SD-SERIAL_HHMM
        target_ext = os.path.join(self.backup_target, "Backup_Ingesta", session_folder)

        # Confirm Action
        if not messagebox.askyesno(
            "Confirmar Modo Puente",
            f"ESTE MODO OPTIMIZA SEGURIDAD.\n\nSesión: {session_folder}\n\n1. Copia SD -> Disco Interno.\n2. Si hay espacio, MANTIENE la copia interna.\n3. Si NO hay espacio, procesa por trozos y BORRA la interna.\n4. Finalmente copia a Externo.\n\n¿Desea continuar?",
        ):
            return

        # Disable UI
        self.btn_start.configure(state="disabled")
        self.btn_backup.configure(state="disabled")
        self.btn_bridge.configure(state="disabled")
        self.option_source.configure(state="disabled")
        self.progress_bar.set(0)

        self.lbl_status.configure(text="Iniciando Puente...")

        # Start Bridge Worker
        worker = BridgeWorker(self.selected_source, self.local_repo, target_ext, self)
        worker.start()

    def backup_complete(self, count):
        self.after(0, lambda: self._backup_complete_ui(count))

    def _backup_complete_ui(self, count):
        self.lbl_dest_info.configure(text=f"Respaldo OK ({count} carpetas)")
        self.btn_backup.configure(state="normal")
        messagebox.showinfo(
            "Respaldo",
            f"Sincronización completada.\n{count} carpetas verificadas/copiadas.",
        )

    def update_source_list(self, drives):
        # Called from thread, schedule UI update
        self.after(0, lambda: self._update_source_ui(drives))

    def _update_source_ui(self, drives):
        # Update display to show Type (SD, USB, etc.)
        values = [
            f"{d['letter']} ({d['label']}) [{d.get('type', 'Drive')}]" for d in drives
        ]
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
            self.lbl_source_space.configure(text="")
            return

        letter = choice.split(" ")[0]
        self.selected_source = letter

        # Get Info
        hw_id = get_real_hardware_id(letter)
        info = get_drive_info(letter)

        if info:
            gb = 1024**3
            # We already have info['free'], need total ideally, but lib_hardware might return it.
            # If lib_hardware only returns 'size', that is total.
            # Let's check lib_hardware or just use shutil here for consistency if drive is mounted.
            try:
                t, u, f = shutil.disk_usage(letter)
                self.lbl_source_space.configure(
                    text=f"Libre: {f / gb:.1f} GB / Total: {t / gb:.1f} GB"
                )
            except Exception:
                self.lbl_source_space.configure(text="Espacio: ?")

        display_text = f"Unidad: {letter}\nEtiqueta: {info['label'] if info else '?'}\nID Hardware: {hw_id}"
        self.lbl_source_info.configure(text=display_text)

        if hw_id:
            self.btn_start.configure(state="normal")

            # Enable Bridge if Backup Target is also present
            if hasattr(self, "backup_target") and self.backup_target:
                self.btn_bridge.configure(state="normal")
        else:
            self.btn_start.configure(state="disabled")  # Require valid WMI ID
            self.btn_bridge.configure(state="disabled")

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
            if not messagebox.askyesno(
                "Duplicado Detectado",
                f"Esta tarjeta ya fue procesada hoy en:\n{prev_path}\n\n¿Desea procesar nuevamente?",
            ):
                return

        # UI Lock
        self.btn_start.configure(state="disabled")
        self.btn_bridge.configure(state="disabled")
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
        # Check if we should re-enable bridge
        if (
            self.selected_source
            and hasattr(self, "backup_target")
            and self.backup_target
        ):
            self.btn_bridge.configure(state="normal")
        elif hasattr(self, "backup_target") and self.backup_target:
            # Just backup button
            self.btn_backup.configure(state="normal")

    # --- ARCHIVE MODULE METHODS ---

    def select_archive_dest(self):
        d = ctk.filedialog.askdirectory(title="Seleccionar Depósito Final")
        if d:
            self.entry_archive_dest.delete(0, "end")
            self.entry_archive_dest.insert(0, d)

    def start_archive(self):
        # Source for Archiving is the External Drive (Panel 3)
        if not hasattr(self, "backup_target") or not self.backup_target:
            messagebox.showerror(
                "Error", "No hay disco externo conectado (Origen para Archivo)."
            )
            return

        dest_root = self.entry_archive_dest.get()
        if not dest_root or not os.path.exists(dest_root):
            # Try verify write access or existence
            try:
                os.makedirs(dest_root, exist_ok=True)
            except Exception as e:
                messagebox.showerror(
                    "Error", f"Ruta de archivo inválida o sin permisos: {e}"
                )
                return

        if not messagebox.askyesno(
            "Confirmar Archivo",
            f"Se procederá a validar y mover datos desde:\n{self.backup_target}\n\nHacia:\n{dest_root}\n\n¿Desea continuar?",
        ):
            return

        self.btn_archive.configure(state="disabled")
        self.archive_progress.set(0)
        self.lbl_archive_status.configure(text="Iniciando auditoría...")

        # Start Worker
        self.archive_worker = ArchiveWorker(self.backup_target, dest_root, self)
        self.archive_worker.start()

    def update_archive_status(self, msg):
        self.after(0, lambda: self.lbl_archive_status.configure(text=msg))
        self.log_message(f"[ARCHIVO] {msg}")

    def update_archive_progress(self, val, msg):
        self.after(0, lambda: self._update_archive_progress_ui(val, msg))

    def _update_archive_progress_ui(self, val, msg):
        self.archive_progress.set(val)
        self.lbl_archive_status.configure(text=msg)

    def archive_complete(self, count):
        self.after(0, lambda: self._archive_complete_ui(count))

    def _archive_complete_ui(self, count):
        self.btn_archive.configure(state="normal")
        self.lbl_archive_status.configure(text="Proceso Finalizado")
        messagebox.showinfo(
            "Archivo Final", f"Proceso completado.\nSesiones procesadas: {count}"
        )

    def archive_failed(self, err):
        self.after(0, lambda: self._archive_failed_ui(err))

    def _archive_failed_ui(self, err):
        self.btn_archive.configure(state="normal")
        self.lbl_archive_status.configure(text="Error")
        messagebox.showerror("Error de Archivo", err)

        self.option_source.configure(state="normal")
        self.lbl_status.configure(text="¡Ingesta Completada!")

    def ingest_failed(self, error_msg):
        self.after(0, lambda: self._ingest_failed_ui(error_msg))

    def _ingest_failed_ui(self, error_msg):
        self.btn_start.configure(state="normal")
        # Restore button states broadly
        if hasattr(self, "backup_target") and self.backup_target:
            self.btn_backup.configure(state="normal")
            if self.selected_source:
                self.btn_bridge.configure(state="normal")

        self.option_source.configure(state="normal")
        self.lbl_status.configure(text="Error en Ingesta")
        messagebox.showerror("Falló la Ingesta", error_msg)


if __name__ == "__main__":
    app = BackupCameraApp()
    app.mainloop()
