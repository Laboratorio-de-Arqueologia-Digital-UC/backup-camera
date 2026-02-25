import os
import shutil
import json
import datetime
import string

def get_drive_roots():
    """Busca discos extraíbles con el marcador .backup_drive y añade el repo local."""
    roots = []
    
    # 1. Buscar discos externos
    available_drives = [
        "%s:" % d for d in string.ascii_uppercase if os.path.exists("%s:" % d)
    ]
    for drive in available_drives:
        if os.path.exists(os.path.join(drive, ".backup_drive")):
            roots.append(drive)
    
    # 2. Añadir repositorio local estándar (Notebook)
    local_repo = "C:\\Backup_Ingesta"
    if os.path.exists(local_repo):
        roots.append(local_repo)
        
    return list(set(roots)) # Evitar duplicados si el externo está en C (raro)

def fix_bridge_structure_in_root(root):
    print(f"\n🔍 Analizando: {root}")

    # 1. Identificar archivos desordenados en ESTA raíz
    manifest_source = None
    for name in ["manifest_bridge.json", "Manifest_bridge.json", "manifest.json"]:
        path = os.path.join(root, name)
        if os.path.exists(path):
            manifest_source = path
            break

    dcim_path = os.path.join(root, "DCIM")
    if not os.path.exists(dcim_path):
        dcim_path = os.path.join(root, "Dcim")

    # Si no hay archivos desordenados aquí, saltar
    if not manifest_source and not os.path.exists(dcim_path):
        print(f"✅ No se detectaron archivos desordenados en {root}")
        return False

    # 2. Generar nombre de sesión
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    session_name = f"{timestamp}_RECOVERED"

    # 3. Determinar carpeta base de ingesta (en la misma unidad)
    # Si es el disco externo, suele ser 'Backup_Ingesta' o 'Back up ingesta'
    # Si es el local, la raíz YA ES 'C:\Backup_Ingesta'
    
    if root.upper().startswith("C:\\BACKUP_INGESTA"):
        backup_ingesta_root = root
    else:
        backup_ingesta_root = os.path.join(root, "Backup_Ingesta")
        if not os.path.exists(backup_ingesta_root):
            if os.path.exists(os.path.join(root, "Back up ingesta")):
                backup_ingesta_root = os.path.join(root, "Back up ingesta")
            else:
                os.makedirs(backup_ingesta_root, exist_ok=True)

    dest_session_path = os.path.join(backup_ingesta_root, session_name)
    os.makedirs(dest_session_path, exist_ok=True)

    print(f"📦 Organizando en: {session_name}")

    # 4. Mover DCIM
    if os.path.exists(dcim_path):
        print(f"➡️ Moviendo DCIM...")
        try:
            shutil.move(dcim_path, os.path.join(dest_session_path, "DCIM"))
        except Exception as e:
            print(f"⚠️ Error moviendo DCIM: {e}")

    # 5. Mover y Renombrar Manifest
    if manifest_source:
        print(f"➡️ Moviendo y renombrando manifiesto...")
        try:
            shutil.move(manifest_source, os.path.join(dest_session_path, "manifest.json"))
        except Exception as e:
            print(f"⚠️ Error moviendo manifiesto: {e}")
            
    return True

def main():
    roots = get_drive_roots()
    if not roots:
        print("❌ No se encontró disco externo ni repositorio local 'C:\\Backup_Ingesta'.")
        return

    any_fixed = False
    for r in roots:
        if fix_bridge_structure_in_root(r):
            any_fixed = True

    if any_fixed:
        print("\n✨ ¡Proceso de limpieza completado!")
    else:
        print("\n✅ Todo parece estar en orden.")

if __name__ == "__main__":
    main()
