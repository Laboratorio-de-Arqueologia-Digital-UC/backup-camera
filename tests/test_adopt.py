import json
import os
import sys

import pytest

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from lib_adopt import (  # noqa: E402
    MODE_SINGLE,
    ORIGIN_MANUAL,
    ORIGIN_SD,
    STATUS_ADOPTED,
    STATUS_DRIFT,
    STATUS_EMPTY,
    STATUS_PROTECTED,
    STATUS_VERIFIED,
    AdoptionError,
    adopt_root,
    adopt_session,
    inspect_root,
    scan_manual_folder,
    verify_session,
)
from lib_archive import ArchiveWorker  # noqa: E402


class MockApp:
    """Doble de la GUI, igual que en tests/test_archive.py."""

    def __init__(self):
        self.log = []
        self.status = ""
        self.completed_count = 0
        self.failed_err = None

    def log_message(self, msg):
        self.log.append(msg)

    def update_archive_status(self, msg):
        self.status = msg

    def update_archive_progress(self, val, msg):
        pass

    def archive_complete(self, count):
        self.completed_count = count

    def archive_failed(self, err):
        self.failed_err = err


@pytest.fixture
def ssd_por_pieza(tmp_path):
    """Simula un SSD con copia manual organizada por pieza."""
    root = tmp_path / "SSD_Piezas"
    contenido = {
        "Pieza_001": {"IMG_0001.CR2": b"AAA", "IMG_0002.CR2": b"BBB"},
        "Pieza_002": {"IMG_0003.CR2": b"CCC"},
    }

    for pieza, archivos in contenido.items():
        carpeta = root / pieza
        carpeta.mkdir(parents=True)
        for nombre, datos in archivos.items():
            (carpeta / nombre).write_bytes(datos)

    return root


def test_adopcion_por_pieza_genera_manifiesto_y_hashes(ssd_por_pieza):
    reportes = adopt_root(str(ssd_por_pieza), operator="Victor Mendez")

    assert [r["status"] for r in reportes] == [STATUS_ADOPTED, STATUS_ADOPTED]

    manifiesto = json.loads(
        (ssd_por_pieza / "Pieza_001" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifiesto["origin"] == ORIGIN_MANUAL
    assert manifiesto["chain_of_custody"] == "partial"
    assert manifiesto["adopted_by"] == "Victor Mendez"
    assert manifiesto["hardware_id"] is None
    assert len(manifiesto["files"]) == 2
    assert all(len(f["hash"]) == 64 for f in manifiesto["files"])

    hashes = json.loads(
        (ssd_por_pieza / "Pieza_001" / "hashes_blake3.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(hashes) == {"IMG_0001.CR2", "IMG_0002.CR2"}


def test_adopcion_no_mueve_ni_altera_archivos(ssd_por_pieza):
    original = (ssd_por_pieza / "Pieza_001" / "IMG_0001.CR2").read_bytes()

    adopt_root(str(ssd_por_pieza), operator="Victor")

    assert (ssd_por_pieza / "Pieza_001" / "IMG_0001.CR2").read_bytes() == original
    assert (ssd_por_pieza / "Pieza_002" / "IMG_0003.CR2").exists()


def test_adopcion_es_idempotente(ssd_por_pieza):
    adopt_root(str(ssd_por_pieza), operator="Victor")
    manifiesto = ssd_por_pieza / "Pieza_001" / "manifest.json"
    contenido_original = manifiesto.read_text(encoding="utf-8")

    segunda = adopt_root(str(ssd_por_pieza), operator="Victor")

    assert [r["status"] for r in segunda] == [STATUS_VERIFIED, STATUS_VERIFIED]
    assert manifiesto.read_text(encoding="utf-8") == contenido_original


def test_verificacion_detecta_desvios(ssd_por_pieza):
    adopt_root(str(ssd_por_pieza), operator="Victor")
    pieza = ssd_por_pieza / "Pieza_001"

    (pieza / "IMG_0001.CR2").write_bytes(b"MODIFICADO")
    (pieza / "IMG_0002.CR2").unlink()
    (pieza / "IMG_9999.CR2").write_bytes(b"NUEVO")

    reporte = verify_session(str(pieza))

    assert reporte["status"] == STATUS_DRIFT
    assert reporte["modified"] == ["IMG_0001.CR2"]
    assert reporte["missing"] == ["IMG_0002.CR2"]
    assert reporte["added"] == ["IMG_9999.CR2"]


def test_no_sobrescribe_manifiesto_de_ingesta_sd(ssd_por_pieza):
    pieza = ssd_por_pieza / "Pieza_002"
    original = {"origin": ORIGIN_SD, "chain_of_custody": "full", "files": []}
    (pieza / "manifest.json").write_text(json.dumps(original), encoding="utf-8")

    reporte = adopt_session(str(pieza), operator="Victor", force=True)

    assert reporte["status"] == STATUS_PROTECTED
    leido = json.loads((pieza / "manifest.json").read_text(encoding="utf-8"))
    assert leido == original


def test_force_regenera_linea_base_adoptada(ssd_por_pieza):
    pieza = ssd_por_pieza / "Pieza_001"
    adopt_session(str(pieza), operator="Victor")

    (pieza / "IMG_0004.CR2").write_bytes(b"DDD")
    reporte = adopt_session(str(pieza), operator="Victor", force=True)

    assert reporte["status"] == STATUS_ADOPTED
    assert reporte["files"] == 3
    assert verify_session(str(pieza))["status"] == STATUS_VERIFIED


def test_modo_carpeta_unica(tmp_path):
    carpeta = tmp_path / "Entrega_Terreno"
    (carpeta / "sub").mkdir(parents=True)
    (carpeta / "IMG_1.CR2").write_bytes(b"X")
    (carpeta / "sub" / "IMG_2.CR2").write_bytes(b"Y")

    assert scan_manual_folder(str(carpeta), MODE_SINGLE) == [str(carpeta)]

    reporte = adopt_session(str(carpeta), operator="Victor")

    assert reporte["status"] == STATUS_ADOPTED
    assert reporte["files"] == 2


def test_carpeta_vacia_se_reporta_sin_adoptar(tmp_path):
    vacia = tmp_path / "Pieza_vacia"
    vacia.mkdir()

    reporte = adopt_session(str(vacia))

    assert reporte["status"] == STATUS_EMPTY
    assert not (vacia / "manifest.json").exists()


def test_scan_falla_si_la_ruta_no_existe(tmp_path):
    with pytest.raises(AdoptionError):
        scan_manual_folder(str(tmp_path / "no_existe"))


def test_inspect_root_distingue_carpetas_adoptables(ssd_por_pieza):
    adopt_session(str(ssd_por_pieza / "Pieza_001"), operator="Victor")

    estado = inspect_root(str(ssd_por_pieza))

    assert estado["self"] is False
    assert [os.path.basename(p) for p in estado["with_manifest"]] == ["Pieza_001"]
    assert [os.path.basename(p) for p in estado["without_manifest"]] == ["Pieza_002"]


def test_archivo_final_acepta_sesiones_adoptadas_en_la_raiz(ssd_por_pieza, tmp_path):
    adopt_root(str(ssd_por_pieza), operator="Victor Mendez")
    destino = tmp_path / "NAS"

    app = MockApp()
    ArchiveWorker(str(ssd_por_pieza), str(destino), app).run()

    assert app.failed_err is None
    assert app.completed_count == 2
    assert (destino / "Pieza_001" / "IMG_0001.CR2").exists()
    assert (destino / "Pieza_002" / "IMG_0003.CR2").exists()

    audit = (destino / "Pieza_001" / "audit_log.txt").read_text(encoding="utf-8")
    assert ORIGIN_MANUAL in audit
    assert "linea base adoptada" in audit
    assert "bit-exacta" in audit


def test_archivo_final_reporta_sesiones_sin_manifiesto(ssd_por_pieza, tmp_path):
    adopt_session(str(ssd_por_pieza / "Pieza_001"), operator="Victor")
    destino = tmp_path / "NAS"

    app = MockApp()
    ArchiveWorker(str(ssd_por_pieza), str(destino), app).run()

    assert app.completed_count == 1
    assert any("sin manifest.json" in msg for msg in app.log)
    assert not (destino / "Pieza_002").exists()


def test_archivo_final_acepta_una_sesion_directa(ssd_por_pieza, tmp_path):
    pieza = ssd_por_pieza / "Pieza_002"
    adopt_session(str(pieza), operator="Victor")
    destino = tmp_path / "NAS"

    app = MockApp()
    ArchiveWorker(str(pieza), str(destino), app).run()

    assert app.completed_count == 1
    assert (destino / "Pieza_002" / "IMG_0003.CR2").exists()
