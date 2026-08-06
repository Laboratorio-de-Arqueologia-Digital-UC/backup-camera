import customtkinter as ctk
import threading
import time
import os
import logging
import json
import shutil
import getpass
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
from lib_adopt import (
    CHAIN_FULL,
    MODE_PER_SUBFOLDER,
    MODE_SINGLE,
    ORIGIN_SD,
    SCHEMA_VERSION,
    AdoptWorker,
    inspect_root,
    summarize,
)

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
                self.check_external_targets()

            except Exception as e:
                logging.error(f"Monitor loop error: {e}")

            time.sleep(2)

    def check_external_targets(self):
        # Scan for drives with .backup_drive file
        found_backups = []
        try:
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

            # Create manifest data structure.
            # origin/chain_of_custody distinguen esta ingesta real desde SD de
            # una linea base adoptada retroactivamente (ver lib_adopt).
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "origin": ORIGIN_SD,
                "chain_of_custody": CHAIN_FULL,
                "entry_stage": "sd",
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
                    pass

                file_hash = secure_copy(src_file, dst_file, progress_cb)

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
            with open(manifest_path, "w", encoding="utf-8") as f:
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

            count = 0
            # Iterate over folders in local repo
            for item in os.listdir(self.src_repo):
                s = os.path.join(self.src_repo, item)
                d = os.path.join(dst_repo, item)
                if os.path.isdir(s):
                    if not os.path.exists(d):
                        # Copy entire tree if missing
                        shutil.copytree(s, d)
                        count += 1
                    else:
                        # Secure policy: never overwrite blindly.
                        pass

            self.app.backup_complete(count)

        except Exception as e:
            logging.error(f"Backup failed: {e}")
            self.app.backup_failed(str(e))


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
        self.backup_target = None
        self.manual_external = None
        self.archive_source = None
        self.adopt_root_path = None
        self.adopt_mode = None
        self.busy = False

        # Disponibilidad de datos por etapa. Antes cada boton dependia del
        # hardware conectado, lo que hacia imposible entrar al flujo en una
        # etapa intermedia (por ejemplo, una copia ya hecha a mano en el SSD).
        self.stage_ready = {
            "source": False,
            "local": False,
            "external": False,
            "archive": False,
        }

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

        self.lbl_source_hint = ctk.CTkLabel(
            self.frame_source,
            text="Sin tarjeta puede entrar en la etapa 2, 3 o 4",
            font=("Arial", 9),
            text_color="#a08050",
            wraplength=260,
        )
        self.lbl_source_hint.pack(pady=5)

        # --- PANEL 2: TRANSIT (Blue) ---
        self.frame_transit = ctk.CTkFrame(self, fg_color="#1a2d3b")  # Dark Blue-ish
        self.frame_transit.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        self.lbl_transit_title = ctk.CTkLabel(
            self.frame_transit,
            text="2. INGESTA",
            font=("Arial", 20, "bold"),
            text_color="#3399ff",
        )
        self.lbl_transit_title.pack(pady=(20, 10))

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
        self.btn_select_repo.pack(pady=(5, 10))

        self.lbl_transit_space = ctk.CTkLabel(
            self.frame_transit, text="", font=("Arial", 12), text_color="#aaaaaa"
        )
        self.lbl_transit_space.pack(pady=2)

        self.btn_start = ctk.CTkButton(
            self.frame_transit,
            text="INICIAR COPIA",
            command=self.start_ingest,
            state="disabled",
            height=45,
            fg_color="#0066cc",
        )
        self.btn_start.pack(pady=(10, 5), padx=20, fill="x")

        # Entrada alternativa: adoptar datos ya copiados manualmente.
        self.btn_adopt = ctk.CTkButton(
            self.frame_transit,
            text="ADOPTAR CARPETA EXISTENTE",
            command=self.start_adopt,
            height=32,
            fg_color="#335577",
            font=("Arial", 11, "bold"),
        )
        self.btn_adopt.pack(pady=(0, 2), padx=20, fill="x")

        self.lbl_adopt_hint = ctk.CTkLabel(
            self.frame_transit,
            text="Copia manual: calcula hashes sin mover archivos",
            font=("Arial", 9),
            text_color="#8899aa",
            wraplength=260,
        )
        self.lbl_adopt_hint.pack(pady=(0, 5))

        self.progress_bar = ctk.CTkProgressBar(self.frame_transit)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=8, padx=20, fill="x")

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

        self.btn_select_external = ctk.CTkButton(
            self.frame_dest,
            text="Elegir destino...",
            command=self.select_external_target,
            width=130,
            height=24,
            fg_color="#2f6b45",
        )
        self.btn_select_external.pack(pady=5)

        self.btn_backup = ctk.CTkButton(
            self.frame_dest,
            text="CLONAR A EXTERNO",
            command=self.start_backup,
            state="disabled",
            fg_color="#009933",
            height=45,
        )
        self.btn_backup.pack(pady=10, padx=20, fill="x")

        # --- PANEL 4: ARCHIVE (Purple/Red) ---
        self.frame_archive = ctk.CTkFrame(self, fg_color="#3b1a3b")  # Dark Purple
        self.frame_archive.grid(row=0, column=3, sticky="nsew", padx=5, pady=5)

        self.lbl_archive_title = ctk.CTkLabel(
            self.frame_archive,
            text="4. ARCHIVO FINAL",
            font=("Arial", 20, "bold"),
            text_color="#d633ff",
        )
        self.lbl_archive_title.pack(pady=(20, 10))

        self.lbl_archive_source = ctk.CTkLabel(
            self.frame_archive,
            text="Sin origen. Use 'Elegir origen...'",
            font=("Arial", 10),
            text_color="gray",
            wraplength=260,
        )
        self.lbl_archive_source.pack(pady=(0, 2))

        self.btn_select_archive_source = ctk.CTkButton(
            self.frame_archive,
            text="Elegir origen...",
            command=self.select_archive_source,
            width=130,
            height=24,
            fg_color="#664477",
        )
        self.btn_select_archive_source.pack(pady=(0, 8))

        self.lbl_archive_info = ctk.CTkLabel(
            self.frame_archive, text="Destino Final:", font=("Arial", 12)
        )
        self.lbl_archive_info.pack(pady=(5, 0))

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
        self.lbl_archive_status.pack(pady=8)

        self.btn_archive = ctk.CTkButton(
            self.frame_archive,
            text="ARCHIVAR Y VALIDAR",
            command=self.start_archive,
            state="disabled",
            fg_color="#800080",
            height=45,
        )
        self.btn_archive.pack(pady=10, padx=20, fill="x")

        self.archive_progress = ctk.CTkProgressBar(self.frame_archive)
        self.archive_progress.set(0)
        self.archive_progress.pack(pady=10, padx=20, fill="x")

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
        self.refresh_stage_state()

    # --- ESTADO POR ETAPAS ---------------------------------------------

    def _local_has_data(self):
        """True si el repositorio local contiene alguna carpeta de sesión."""
        try:
            for name in os.listdir(self.local_repo):
                if os.path.isdir(os.path.join(self.local_repo, name)):
                    return True
        except OSError:
            return False
        return False

    def effective_archive_source(self):
        """Origen de la etapa 4: elección manual o disco externo detectado."""
        return self.archive_source or self.backup_target

    def refresh_stage_state(self):
        """Recalcula la disponibilidad de datos y sincroniza los botones."""
        self.stage_ready["local"] = self._local_has_data()
        self.stage_ready["archive"] = bool(self.effective_archive_source())
        self.refresh_stage_buttons()

    def refresh_stage_buttons(self):
        """
        Habilita cada etapa según los datos disponibles en disco.

        Sustituye la lógica anterior, que ataba los botones a la presencia de
        hardware (tarjeta SD con ID WMI válido o disco con .backup_drive) y
        por lo tanto bloqueaba el ingreso en etapas intermedias.
        """
        if self.busy:
            for btn in (
                self.btn_start,
                self.btn_adopt,
                self.btn_backup,
                self.btn_bridge,
                self.btn_archive,
            ):
                btn.configure(state="disabled")
            self.option_source.configure(state="disabled")
            return

        self.option_source.configure(state="normal")
        self.btn_adopt.configure(state="normal")

        self.btn_start.configure(
            state="normal" if self.stage_ready["source"] else "disabled"
        )

        can_backup = self.stage_ready["local"] and self.stage_ready["external"]
        self.btn_backup.configure(state="normal" if can_backup else "disabled")

        can_bridge = self.stage_ready["source"] and self.stage_ready["external"]
        self.btn_bridge.configure(state="normal" if can_bridge else "disabled")

        self.btn_archive.configure(
            state="normal" if self.stage_ready["archive"] else "disabled"
        )

    def change_local_repo(self):
        root = ctk.filedialog.askdirectory(
            initialdir=self.local_repo, title="Seleccionar Carpeta de Ingesta"
        )
        if root:
            self.local_repo = root
            self.lbl_local_repo.configure(text=f"Destino: {self.local_repo}")
            self.update_local_space()
            self.refresh_stage_state()

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
        x_int = w * 0.5

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
        detected = drives[0] if drives else None

        # Una elección manual tiene prioridad sobre la detección automática,
        # para permitir respaldar a un destino sin marcador .backup_drive.
        if self.manual_external:
            target = self.manual_external
            label = f"Destino manual:\n{target}"
            color = "#ffcc00"
        elif detected:
            target = detected
            label = f"Destino Detectado: {target}"
            color = "#00cc66"
        else:
            target = None
            label = "Conecte Disco Externo\n(o use 'Elegir destino...')"
            color = "gray"

        self.backup_target = target
        self.stage_ready["external"] = bool(target)
        self.lbl_dest_info.configure(text=label, text_color=color)

        if target:
            try:
                total, used, free = shutil.disk_usage(target)
                gb = 1024**3
                self.lbl_dest_space.configure(
                    text=f"Libre: {free / gb:.1f} GB / Total: {total / gb:.1f} GB"
                )
            except Exception:
                self.lbl_dest_space.configure(text="?")
        else:
            self.lbl_dest_space.configure(text="")

        self.refresh_stage_state()
        self._refresh_archive_source_label()

    def select_external_target(self):
        """
        Designa manualmente el destino de la etapa 3 cuando no hay un disco
        con el marcador .backup_drive.
        """
        folder = ctk.filedialog.askdirectory(title="Seleccionar Destino de Respaldo")
        if not folder:
            return

        marker = os.path.join(folder, ".backup_drive")
        if not os.path.exists(marker):
            answer = messagebox.askyesnocancel(
                "Destino sin marcador",
                f"{folder}\n\nEsta ubicación no tiene el archivo marcador "
                ".backup_drive, que es la salvaguarda contra clonar al disco "
                "equivocado.\n\n"
                "Sí = crear el marcador y usar este destino.\n"
                "No = usar el destino solo en esta sesión.\n"
                "Cancelar = abortar.",
            )
            if answer is None:
                return
            if answer:
                try:
                    with open(marker, "w", encoding="utf-8") as handle:
                        handle.write("backup-camera\n")
                    self.log_message(f"Marcador .backup_drive creado en {folder}")
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo crear marcador: {e}")
                    return

        self.manual_external = folder
        self.log_message(f"Destino externo manual: {folder}")
        self._update_backup_ui([])

    def start_backup(self):
        # Update local space periodically or before action
        self.update_local_space()
        # Only start if we have something in local repo
        if not os.path.exists(self.local_repo) or not os.listdir(self.local_repo):
            messagebox.showwarning("Aviso", "No hay datos locales para respaldar.")
            return

        if not self.backup_target:
            messagebox.showerror(
                "Error",
                "No hay destino externo. Conecte un disco con .backup_drive o "
                "use 'Elegir destino...'.",
            )
            return

        self.busy = True
        self.refresh_stage_buttons()
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

        # 2. Build final external path (nested)
        target_ext = os.path.join(self.backup_target, "Backup_Ingesta", session_folder)

        # Confirm Action
        if not messagebox.askyesno(
            "Confirmar Modo Puente",
            f"ESTE MODO OPTIMIZA SEGURIDAD.\n\nSesión: {session_folder}\n\n"
            "1. Copia SD -> Disco Interno.\n"
            "2. Si hay espacio, MANTIENE la copia interna.\n"
            "3. Si NO hay espacio, procesa por trozos y BORRA la interna.\n"
            "4. Finalmente copia a Externo.\n\n¿Desea continuar?",
        ):
            return

        # Disable UI
        self.busy = True
        self.refresh_stage_buttons()
        self.progress_bar.set(0)

        self.lbl_status.configure(text="Iniciando Puente...")

        # Start Bridge Worker
        worker = BridgeWorker(self.selected_source, self.local_repo, target_ext, self)
        worker.start()

    def backup_complete(self, count):
        self.after(0, lambda: self._backup_complete_ui(count))

    def _backup_complete_ui(self, count):
        self.busy = False
        self.lbl_dest_info.configure(text=f"Respaldo OK ({count} carpetas)")
        self.refresh_stage_state()
        messagebox.showinfo(
            "Respaldo",
            f"Sincronización completada.\n{count} carpetas verificadas/copiadas.",
        )

    def backup_failed(self, err):
        self.after(0, lambda: self._backup_failed_ui(err))

    def _backup_failed_ui(self, err):
        self.busy = False
        self.refresh_stage_state()
        self.lbl_dest_info.configure(text="Error en respaldo")
        messagebox.showerror("Error Respaldo", err)

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
            self.selected_source = None
            self.stage_ready["source"] = False
            self.refresh_stage_state()
        else:
            current_vals = self.option_source.cget("values")
            if set(values) != set(current_vals) and current_vals != ["Sin Origen"]:
                # Only update if changed to avoid resetting selection
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
            try:
                t, u, f = shutil.disk_usage(letter)
                self.lbl_source_space.configure(
                    text=f"Libre: {f / gb:.1f} GB / Total: {t / gb:.1f} GB"
                )
            except Exception:
                self.lbl_source_space.configure(text="Espacio: ?")

        label = info["label"] if info else "?"
        display_text = f"Unidad: {letter}\nEtiqueta: {label}\nID Hardware: {hw_id}"
        self.lbl_source_info.configure(text=display_text)

        # La etapa 1 sigue exigiendo un ID de hardware válido: es el núcleo de
        # la cadena de custodia completa. Las demás etapas ya no dependen de él.
        self.stage_ready["source"] = bool(hw_id)
        self.refresh_stage_state()

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
                f"Esta tarjeta ya fue procesada hoy en:\n{prev_path}\n\n"
                "¿Desea procesar nuevamente?",
            ):
                return

        # UI Lock
        self.busy = True
        self.refresh_stage_buttons()
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
        self.busy = False
        self.lbl_status.configure(text="¡Ingesta Completada!")
        self.refresh_stage_state()

        # Calcular información de la sesión copiada
        try:
            file_count = sum(len(files) for _, _, files in os.walk(path))
            total_bytes = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, files in os.walk(path)
                for f in files
            )
            size_mb = total_bytes / (1024 * 1024)
            session_name = os.path.basename(path)
            finished_at = time.strftime("%d/%m/%Y %H:%M:%S")
        except Exception:
            file_count, size_mb, session_name, finished_at = "?", 0, path, ""

        messagebox.showinfo(
            "Copia Completada",
            f"La copia finalizó correctamente.\n\n"
            f"Sesión:       {session_name}\n"
            f"Archivos:     {file_count} archivo(s)\n"
            f"Tamaño:       {size_mb:.1f} MB\n"
            f"Destino:      {path}\n"
            f"Finalizado:   {finished_at}",
        )

    def ingest_failed(self, error_msg):
        self.after(0, lambda: self._ingest_failed_ui(error_msg))

    def _ingest_failed_ui(self, error_msg):
        self.busy = False
        self.refresh_stage_state()
        self.lbl_status.configure(text="Error en Ingesta")
        messagebox.showerror("Falló la Ingesta", error_msg)

    # --- ADOPCIÓN DE COPIAS MANUALES -----------------------------------

    def start_adopt(self):
        """
        Entrada alternativa a la etapa 2: adoptar una copia hecha a mano.

        No mueve ni modifica archivos; solo construye la línea base de
        integridad que las etapas 3 y 4 necesitan para operar.
        """
        folder = ctk.filedialog.askdirectory(
            initialdir=self.local_repo, title="Seleccionar Carpeta Ya Copiada"
        )
        if not folder:
            return

        answer = messagebox.askyesnocancel(
            "Estructura de la carpeta",
            f"{folder}\n\n"
            "¿Cada subcarpeta es una sesión independiente (por ejemplo, una "
            "carpeta por pieza)?\n\n"
            "Sí = tratar cada subcarpeta como una sesión.\n"
            "No = tratar toda la carpeta como una sola sesión.\n"
            "Cancelar = abortar.",
        )
        if answer is None:
            return

        mode = MODE_PER_SUBFOLDER if answer else MODE_SINGLE
        self.run_adoption(folder, mode)

    def run_adoption(self, folder, mode, entry_stage="local_ssd"):
        """Lanza el AdoptWorker tras confirmar el alcance con el usuario."""
        if mode == MODE_PER_SUBFOLDER:
            descripcion = "una sesión por subcarpeta"
        else:
            descripcion = "toda la carpeta como una sola sesión"

        if not messagebox.askyesno(
            "Confirmar Adopción",
            f"Origen: {folder}\nModo: {descripcion}\n\n"
            "Se calculará el hash BLAKE3 de cada archivo y se escribirá "
            "manifest.json + hashes_blake3.json en cada sesión.\n\n"
            "NO se mueven, copian ni modifican los archivos originales.\n\n"
            "IMPORTANTE: la cadena de custodia quedará marcada como PARCIAL, "
            "porque la copia se realizó fuera del sistema y no puede "
            "certificarse equivalencia bit-exacta con la tarjeta SD.\n\n"
            "¿Desea continuar?",
        ):
            return

        self.adopt_root_path = folder
        self.adopt_mode = mode
        self.busy = True
        self.refresh_stage_buttons()
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Adoptando carpeta existente...")
        self.log_message(f"Adopción iniciada: {folder} ({descripcion})")

        worker = AdoptWorker(
            folder,
            self,
            mode=mode,
            operator=getpass.getuser(),
            notes=f"Copia manual adoptada desde {folder}",
            entry_stage=entry_stage,
        )
        worker.start()

    def update_adopt_status(self, msg):
        self.after(0, lambda: self.lbl_status.configure(text=msg))

    def update_adopt_progress(self, val, msg):
        self.after(0, lambda: self._update_progress_ui(val, msg))

    def adopt_complete(self, reports):
        self.after(0, lambda: self._adopt_complete_ui(reports))

    def _adopt_complete_ui(self, reports):
        self.busy = False
        summary = summarize(reports)

        lineas = []
        for status, count in sorted(summary["by_status"].items()):
            lineas.append(f"  {status}: {count}")
        detalle = "\n".join(lineas)

        root = self.adopt_root_path
        if root:
            # La carpeta adoptada queda disponible como origen de la etapa 4.
            self.archive_source = root

        self.progress_bar.set(0 if summary["has_problems"] else 1)
        self.lbl_status.configure(text="Adopción finalizada")
        self.log_message(
            f"Adopción: {summary['sessions']} sesión(es), "
            f"{summary['files']} archivo(s)"
        )

        if summary["has_problems"]:
            messagebox.showwarning(
                "Adopción con observaciones",
                f"Sesiones: {summary['sessions']}\n"
                f"Archivos: {summary['files']}\n\n"
                f"{detalle}\n\n"
                "Revise el registro: hay desvíos de integridad o manifiestos "
                "protegidos que no se re-generaron.",
            )
        else:
            messagebox.showinfo(
                "Adopción Completada",
                f"Sesiones: {summary['sessions']}\n"
                f"Archivos: {summary['files']}\n\n"
                f"{detalle}\n\n"
                "Ya puede continuar en la etapa 3 (respaldo externo) o en la "
                "etapa 4 (archivo final) usando esta carpeta como origen.",
            )

        self._offer_as_local_repo(root)
        self.refresh_stage_state()
        self._refresh_archive_source_label()

    def _offer_as_local_repo(self, root):
        """
        Ofrece usar la carpeta adoptada como repositorio local, para poder
        clonarla al disco externo en la etapa 3.
        """
        if not root:
            return

        if self.adopt_mode == MODE_SINGLE:
            candidato = os.path.dirname(os.path.normpath(root))
        else:
            candidato = root

        if not candidato:
            return

        if os.path.normpath(candidato) == os.path.normpath(self.local_repo):
            return

        if messagebox.askyesno(
            "Usar como repositorio local",
            f"¿Desea usar\n{candidato}\ncomo repositorio local, para poder "
            "clonarlo al disco externo en la etapa 3?",
        ):
            self.local_repo = candidato
            self.lbl_local_repo.configure(text=f"Destino: {self.local_repo}")
            self.update_local_space()

    def adopt_failed(self, err):
        self.after(0, lambda: self._adopt_failed_ui(err))

    def _adopt_failed_ui(self, err):
        self.busy = False
        self.refresh_stage_state()
        self.lbl_status.configure(text="Error en adopción")
        messagebox.showerror("Falló la Adopción", err)

    # --- ARCHIVE MODULE METHODS ---

    def select_archive_dest(self):
        d = ctk.filedialog.askdirectory(title="Seleccionar Depósito Final")
        if d:
            self.entry_archive_dest.delete(0, "end")
            self.entry_archive_dest.insert(0, d)

    def select_archive_source(self):
        """
        Permite archivar desde cualquier ruta (SSD, disco externo o carpeta
        local), sin exigir que el monitor haya detectado un disco.
        """
        folder = ctk.filedialog.askdirectory(title="Seleccionar Origen a Archivar")
        if not folder:
            return

        self.archive_source = folder
        self.refresh_stage_state()
        self._refresh_archive_source_label()
        self.log_message(f"Origen de archivo: {folder}")

        pendientes = self._pending_adoption(folder)
        if pendientes:
            if messagebox.askyesno(
                "Carpetas sin línea base",
                f"{len(pendientes)} carpeta(s) de este origen no tienen "
                "manifest.json y serían omitidas al archivar.\n\n"
                "¿Desea adoptarlas ahora? Se calcularán sus hashes sin mover "
                "los archivos.",
            ):
                self.run_adoption(folder, MODE_PER_SUBFOLDER, entry_stage="archive")

    def _pending_adoption(self, folder):
        """Subcarpetas sin manifiesto que quedarían fuera del archivo final."""
        target = folder
        nested = os.path.join(folder, "Backup_Ingesta")
        if os.path.isdir(nested):
            target = nested

        state = inspect_root(target)
        if state["self"]:
            return []
        return state["without_manifest"]

    def _refresh_archive_source_label(self):
        source = self.effective_archive_source()
        if source:
            origen = "manual" if self.archive_source else "disco externo"
            self.lbl_archive_source.configure(
                text=f"Origen ({origen}):\n{source}", text_color="#dd99ff"
            )
        else:
            self.lbl_archive_source.configure(
                text="Sin origen. Use 'Elegir origen...'", text_color="gray"
            )

    def start_archive(self):
        src_root = self.effective_archive_source()
        if not src_root:
            messagebox.showerror(
                "Error",
                "No hay origen para archivar.\n\nConecte un disco externo o "
                "use 'Elegir origen...' para archivar desde cualquier carpeta.",
            )
            return

        dest_root = self.entry_archive_dest.get()
        if not dest_root:
            messagebox.showerror("Error", "Indique la ruta de destino final.")
            return

        if not os.path.exists(dest_root):
            try:
                os.makedirs(dest_root, exist_ok=True)
            except Exception as e:
                messagebox.showerror(
                    "Error", f"Ruta de archivo inválida o sin permisos: {e}"
                )
                return

        # Antes, una carpeta sin manifiesto se omitía en silencio y el proceso
        # terminaba con "0 sesiones". Ahora se avisa y se ofrece adoptarla.
        pendientes = self._pending_adoption(src_root)
        if pendientes:
            answer = messagebox.askyesnocancel(
                "Carpetas sin línea base",
                f"{len(pendientes)} carpeta(s) no tienen manifest.json y serían "
                "omitidas al archivar.\n\n"
                "Sí = adoptarlas ahora (luego vuelva a archivar).\n"
                "No = archivar solo lo que ya tiene manifiesto.\n"
                "Cancelar = abortar.",
            )
            if answer is None:
                return
            if answer:
                self.run_adoption(src_root, MODE_PER_SUBFOLDER, entry_stage="archive")
                return

        if not messagebox.askyesno(
            "Confirmar Archivo",
            f"Se procederá a validar y copiar datos desde:\n{src_root}\n\n"
            f"Hacia:\n{dest_root}\n\n¿Desea continuar?",
        ):
            return

        self.busy = True
        self.refresh_stage_buttons()
        self.archive_progress.set(0)
        self.lbl_archive_status.configure(text="Iniciando auditoría...")

        # Start Worker
        self.archive_worker = ArchiveWorker(src_root, dest_root, self)
        self.archive_worker.start()

    def update_archive_status(self, msg):
        self.after(0, lambda: self.lbl_archive_status.configure(text=msg))
        self.after(0, lambda: self.log_message(f"[ARCHIVO] {msg}"))

    def update_archive_progress(self, val, msg):
        self.after(0, lambda: self._update_archive_progress_ui(val, msg))

    def _update_archive_progress_ui(self, val, msg):
        self.archive_progress.set(val)
        self.lbl_archive_status.configure(text=msg)

    def archive_complete(self, count):
        self.after(0, lambda: self._archive_complete_ui(count))

    def _archive_complete_ui(self, count):
        self.busy = False
        self.refresh_stage_state()
        self.lbl_archive_status.configure(text="Proceso Finalizado")
        messagebox.showinfo(
            "Archivo Final", f"Proceso completado.\nSesiones procesadas: {count}"
        )

    def archive_failed(self, err):
        self.after(0, lambda: self._archive_failed_ui(err))

    def _archive_failed_ui(self, err):
        self.busy = False
        self.refresh_stage_state()
        self.lbl_archive_status.configure(text="Error")
        messagebox.showerror("Error de Archivo", err)


if __name__ == "__main__":
    app = BackupCameraApp()
    app.mainloop()
