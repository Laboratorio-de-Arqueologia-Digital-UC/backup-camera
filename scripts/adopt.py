"""
CLI de adopcion: ingresar al flujo en cualquier etapa, sin interfaz grafica.

Genera la linea base de integridad (manifest.json + hashes_blake3.json) sobre
datos que ya fueron copiados manualmente, sin mover ni alterar los archivos.

Uso tipico (copia manual en SSD, una carpeta por pieza):

    uv run python scripts/adopt.py --root "D:\\Piezas" --mode per-piece \\
        --operator "Victor Mendez" --notes "Respaldo manual de terreno"

Verificacion posterior (no escribe nada, exit code 1 si hay desvios):

    uv run python scripts/adopt.py --root "D:\\Piezas" --verify
"""

import argparse
import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from lib_adopt import (  # noqa: E402
    MODE_PER_SUBFOLDER,
    MODE_SINGLE,
    AdoptionError,
    adopt_root,
    summarize,
)

MODE_ALIASES = {
    "per-piece": MODE_PER_SUBFOLDER,
    "per-subfolder": MODE_PER_SUBFOLDER,
    "single": MODE_SINGLE,
}


def human_size(num_bytes):
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Genera la linea base de integridad (manifest.json + "
            "hashes_blake3.json) sobre copias hechas manualmente."
        )
    )
    parser.add_argument("--root", required=True, help="Carpeta raiz de la copia.")
    parser.add_argument(
        "--mode",
        default="per-piece",
        choices=sorted(MODE_ALIASES),
        help="per-piece: una sesion por subcarpeta. single: la raiz es una sesion.",
    )
    parser.add_argument(
        "--operator",
        default=None,
        help="Responsable de la adopcion.",
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="Observaciones de procedencia.",
    )
    parser.add_argument(
        "--entry-stage",
        default="local_ssd",
        help="Etapa de ingreso al flujo (local_ssd, external, archive).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Solo verifica contra el manifiesto existente; no escribe.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-genera la linea base de sesiones ya adoptadas.",
    )
    return parser.parse_args(argv)


def print_report(report):
    print(
        f"  [{report['status'].upper():>12}] {report['name']}  "
        f"{report['files']} archivo(s)  {human_size(report['bytes'])}"
    )

    for label, key in (
        ("modificado", "modified"),
        ("faltante", "missing"),
        ("nuevo", "added"),
    ):
        for item in report.get(key) or []:
            print(f"        - {label}: {item}")

    if report.get("message"):
        print(f"        {report['message']}")


def main(argv=None):
    args = parse_args(argv)

    try:
        reports = adopt_root(
            args.root,
            mode=MODE_ALIASES[args.mode],
            operator=args.operator,
            notes=args.notes,
            entry_stage=args.entry_stage,
            force=args.force,
            verify_only=args.verify,
        )
    except AdoptionError as exc:
        print(f"ERROR: {exc}")
        return 2

    modo = args.mode + (" (solo verificacion)" if args.verify else "")
    print(f"\nRaiz: {os.path.abspath(args.root)}")
    print(f"Modo: {modo}\n")

    for report in reports:
        print_report(report)

    summary = summarize(reports)
    print(
        f"\nResumen: {summary['sessions']} sesion(es), "
        f"{summary['files']} archivo(s), {human_size(summary['bytes'])}"
    )
    for status, count in sorted(summary["by_status"].items()):
        print(f"  {status}: {count}")

    if summary["has_problems"]:
        print("\nATENCION: hay desvios de integridad o manifiestos protegidos.")
        return 1

    print("\nListo. Las sesiones ya pueden entrar a las etapas 3 y 4 del flujo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
