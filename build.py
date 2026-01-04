import PyInstaller.__main__

def build():
    print("Building Backup Camera Executable...")
    
    # Define options
    options = [
        'src/main.py',                 # Script to pack
        '--name=BackupCamera',         # Executable name
        '--onefile',                   # Single EXE
        '--noconsole',                 # No terminal window
        '--clean',                     # Clean cache
        '--add-data=src;.',            # Include src folder content if needed (imports handle this mostly)
        '--collect-all=customtkinter', # Ensure CTK assets are collected
        '--log-level=WARN',
    ]
    
    PyInstaller.__main__.run(options)
    print("Build complete. Output in /dist")

if __name__ == "__main__":
    build()
