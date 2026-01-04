import PyInstaller.__main__


def build():
    print("Building Backup Camera Executable...")

    # Read version from pyproject.toml
    version = "0.0.0"
    try:
        with open("pyproject.toml", "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("version"):
                    # Extract string inside quotes: version = "0.1.0"
                    version = line.split("=")[1].strip().strip('"').strip("'")
                    break
    except Exception as e:
        print(f"Warning: Could not read version: {e}")

    exe_name = f"BackupCamera_v{version}"

    # Define options
    options = [
        "src/main.py",  # Script to pack
        "--name=%s" % exe_name,  # Executable name
        "--onefile",  # Single EXE
        "--noconsole",  # No terminal window
        "--clean",  # Clean cache
        "--add-data=src;.",  # Include src folder content if needed (imports handle this mostly)
        "--collect-all=customtkinter",  # Ensure CTK assets are collected
        "--log-level=WARN",
        "--distpath=dist",  # Output directory for the executable
        "--workpath=build",  # Directory for temporary files
        "--specpath=build",  # Directory for the .spec file
    ]

    PyInstaller.__main__.run(options)
    print("Build complete. Output in /dist")


if __name__ == "__main__":
    build()
