import json
import os
import sys
import threading

import pytest

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from lib_adopt import (  # noqa: E402
    MODE_SINGLE,
    ORIGIN_MANUAL,
    ORIGIN_SD,
    STATUS_ADOPTED,
    STATUS_CANCELLED,
    STATUS_DRIFT,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_LOOSE,
    STATUS_PROTECTED,
    STATUS_VERIFIED,
    AdoptionError,
    adopt_root,
    adopt_session,
    collect_advisories,
    collect_duplicate_warnings,
    inspect_root,
    pending_adoption,
    scan_manual_folder,
    summarize,
    verify_session,
)
from lib_archive import ArchiveWorker  # noqa: E402
from lib_storage import normalize_root  # noqa: E402


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


# --- Adopcion basica -------------------------------------------------------


def test_adopcion_por_pieza_genera_manifiesto_y_hashes(ssd_por_pieza):
    reportes = adopt_root(str(ssd_por_pieza), operator="Victor Mendez")

    assert [r["status"] for r in reportes] == [STATUS_ADOPTED, STATUS_ADOPTED]

    manifest_path = ssd_por_pieza / "Pieza_001" / "manifest.json"
    manifiesto = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifiesto["origin"] == ORIGIN_MANUAL
    assert manifiesto["chain_of_custody"] == "partial"
    assert manifiesto["adopted_by"] == "Victor Mendez"
    assert manifiesto["hardware_id"] is None
    assert len(manifiesto["files"]) == 2
    assert all(len(f["hash"]) == 64 for f in manifiesto["files"])

    hashes_path = ssd_por_pieza / "Pieza_001" / "hashes_blake3.json"
    hashes = json.loads(hashes_path.read_text(encoding="utf-8"))

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


def test_verificacion_detecta_un_solo_byte_alterado(tmp_path):
    """
    Corrupcion silenciosa: un bit distinto en medio de un archivo grande.

    Es el escenario que justifica todo el sistema, asi que se comprueba de
    forma explicita y con fsync, para que la escritura llegue al disco.
    """
    pieza = tmp_path / "Pieza_X"
    pieza.mkdir()
    archivo = pieza / "IMG_0001.CR2"
    archivo.write_bytes(bytes(range(256)) * 4096)  # 1 MB determinista

    assert adopt_session(str(pieza), operator="prueba")["status"] == STATUS_ADOPTED

    with open(archivo, "r+b") as handle:
        handle.seek(1000)
        original = handle.read(1)[0]
        handle.seek(1000)
        handle.write(bytes([original ^ 0xFF]))
        handle.flush()
        os.fsync(handle.fileno())

    reporte = verify_session(str(pieza))

    assert reporte["status"] == STATUS_DRIFT
    assert reporte["modified"] == ["IMG_0001.CR2"]
    assert summarize([reporte])["has_problems"] is True


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


def test_pending_adoption_resuelve_backup_ingesta(tmp_path):
    externo = tmp_path / "Externo"
    sesion = externo / "Backup_Ingesta" / "Sesion_A"
    sesion.mkdir(parents=True)
    (sesion / "IMG.CR2").write_bytes(b"Z")

    pendientes = pending_adoption(str(externo))

    assert [os.path.basename(p) for p in pendientes] == ["Sesion_A"]

    adopt_session(str(sesion), operator="Victor")
    assert pending_adoption(str(externo)) == []


# --- Severidad: avisos frente a problemas de integridad --------------------


def test_archivos_sueltos_se_reportan_pero_no_bloquean(ssd_por_pieza):
    """
    Un archivo suelto es una observacion sobre la organizacion, no una falla.

    Si marcara has_problems, la verificacion periodica alertaria siempre
    (esos archivos suelen quedarse ahi) y la alarma perderia todo su valor.
    """
    (ssd_por_pieza / "notas_terreno.txt").write_bytes(b"apuntes")

    reportes = adopt_root(str(ssd_por_pieza), operator="Victor")
    sueltos = [r for r in reportes if r["status"] == STATUS_LOOSE]
    summary = summarize(reportes)

    assert len(sueltos) == 1
    assert sueltos[0]["loose"] == ["notas_terreno.txt"]

    # Visible en el reporte...
    assert summary["has_advisories"] is True
    assert summary["advisories"] == 1
    assert collect_advisories(reportes)

    # ...pero sin bloquear el flujo ni contarse como sesion.
    assert summary["has_problems"] is False
    assert summary["sessions"] == 2


def test_un_desvio_bloquea_aunque_haya_avisos(ssd_por_pieza):
    """La integridad manda: un drift alerta incluso con avisos presentes."""
    (ssd_por_pieza / "notas_terreno.txt").write_bytes(b"apuntes")
    adopt_root(str(ssd_por_pieza), operator="Victor")

    (ssd_por_pieza / "Pieza_001" / "IMG_0001.CR2").write_bytes(b"CORRUPTO")

    summary = summarize(adopt_root(str(ssd_por_pieza), verify_only=True))

    assert summary["has_problems"] is True
    assert summary["has_advisories"] is True
    assert summary["by_status"][STATUS_DRIFT] == 1


def test_error_de_lectura_si_bloquea(ssd_por_pieza, monkeypatch):
    """Un archivo ilegible es un problema de integridad, no un aviso."""
    import lib_adopt

    real_hash_file = lib_adopt.hash_file

    def hash_con_falla(path, callback_progress=None):
        if path.endswith("IMG_0001.CR2"):
            raise OSError("El proceso no tiene acceso al archivo")
        return real_hash_file(path, callback_progress)

    monkeypatch.setattr(lib_adopt, "hash_file", hash_con_falla)

    reportes = adopt_root(str(ssd_por_pieza), operator="Victor")
    estados = {r["name"]: r["status"] for r in reportes}

    assert estados["Pieza_001"] == STATUS_ERROR
    assert estados["Pieza_002"] == STATUS_ADOPTED
    assert summarize(reportes)["has_problems"] is True

    # El aislamiento se mantiene: la otra pieza si quedo adoptada.
    assert (ssd_por_pieza / "Pieza_002" / "manifest.json").exists()
    assert not (ssd_por_pieza / "Pieza_001" / "manifest.json").exists()


# --- Robustez de la adopcion ----------------------------------------------


def test_cancelacion_detiene_la_adopcion(ssd_por_pieza):
    stop_event = threading.Event()
    stop_event.set()

    reportes = adopt_root(str(ssd_por_pieza), stop_event=stop_event)

    assert [r["status"] for r in reportes] == [STATUS_CANCELLED]
    assert not (ssd_por_pieza / "Pieza_001" / "manifest.json").exists()


def test_colision_de_basenames_se_reporta(tmp_path):
    """hashes_blake3.json aplana a basename: hay que avisar de la perdida."""
    sesion = tmp_path / "Sesion"
    (sesion / "a").mkdir(parents=True)
    (sesion / "b").mkdir(parents=True)
    (sesion / "a" / "IMG_0001.CR2").write_bytes(b"UNO")
    (sesion / "b" / "IMG_0001.CR2").write_bytes(b"DOS")

    reporte = adopt_session(str(sesion), operator="Victor")

    assert reporte["status"] == STATUS_ADOPTED
    assert reporte["files"] == 2
    assert "IMG_0001.CR2" in reporte["duplicate_basenames"]

    # El manifiesto conserva ambas rutas; el mapa plano solo una clave.
    hashes_path = sesion / "hashes_blake3.json"
    hashes = json.loads(hashes_path.read_text(encoding="utf-8"))

    assert len(hashes) == 1
    assert collect_duplicate_warnings([reporte])


def test_normalize_root_convierte_unidad_en_ruta_absoluta():
    assert normalize_root("E:") == "E:" + os.sep
    assert normalize_root("E:" + os.sep) == "E:" + os.sep
    assert normalize_root("") == ""
    assert normalize_root(None) is None


# --- Archivo final --------------------------------------------------------


def test_archivo_final_acepta_sesiones_adoptadas_en_la_raiz(ssd_por_pieza, tmp_path):
    adopt_root(str(ssd_por_pieza), operator="Victor Mendez")
    destino = tmp_path / "Deposito"

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
    destino = tmp_path / "Deposito"

    app = MockApp()
    ArchiveWorker(str(ssd_por_pieza), str(destino), app).run()

    assert app.completed_count == 1
    assert any("sin manifest.json" in msg for msg in app.log)
    assert not (destino / "Pieza_002").exists()


def test_archivo_final_acepta_una_sesion_directa(ssd_por_pieza, tmp_path):
    pieza = ssd_por_pieza / "Pieza_002"
    adopt_session(str(pieza), operator="Victor")
    destino = tmp_path / "Deposito"

    app = MockApp()
    ArchiveWorker(str(pieza), str(destino), app).run()

    assert app.completed_count == 1
    assert (destino / "Pieza_002" / "IMG_0003.CR2").exists()


def test_archivo_final_rechaza_origen_igual_a_destino(ssd_por_pieza):
    """secure_copy trunca el destino: copiar sobre si mismo destruye el dato."""
    adopt_root(str(ssd_por_pieza), operator="Victor")

    app = MockApp()
    ArchiveWorker(str(ssd_por_pieza), str(ssd_por_pieza), app).run()

    assert app.failed_err is not None
    assert "misma carpeta" in app.failed_err
    assert app.completed_count == 0
    # Lo esencial: el archivo original sigue intacto, no truncado a 0 bytes.
    assert (ssd_por_pieza / "Pieza_001" / "IMG_0001.CR2").read_bytes() == b"AAA"


def test_archivo_final_rechaza_sesion_con_origen_igual_a_destino(tmp_path):
    """Caso real: origen 'E:\\' y destino final 'E:\\Backup_Ingesta'."""
    externo = tmp_path / "Externo"
    contenedor = externo / "Backup_Ingesta"
    sesion = contenedor / "Sesion_A"
    sesion.mkdir(parents=True)
    (sesion / "IMG.CR2").write_bytes(b"DATOS_IMPORTANTES")
    adopt_session(str(sesion), operator="Victor")

    app = MockApp()
    ArchiveWorker(str(externo), str(contenedor), app).run()

    assert app.completed_count == 0
    assert any("mismo origen" in msg for msg in app.log)
    assert (sesion / "IMG.CR2").read_bytes() == b"DATOS_IMPORTANTES"


def test_archivo_final_no_sobrescribe_sesiones_homonimas(tmp_path):
    """Dos SSD distintos pueden traer una 'Pieza_001' con contenido distinto."""
    destino = tmp_path / "Deposito"

    primero = tmp_path / "SSD_A"
    (primero / "Pieza_001").mkdir(parents=True)
    (primero / "Pieza_001" / "IMG.CR2").write_bytes(b"PRIMERO")
    adopt_root(str(primero), operator="Victor")

    segundo = tmp_path / "SSD_B"
    (segundo / "Pieza_001").mkdir(parents=True)
    (segundo / "Pieza_001" / "IMG.CR2").write_bytes(b"SEGUNDO")
    adopt_root(str(segundo), operator="Victor")

    app_a = MockApp()
    ArchiveWorker(str(primero), str(destino), app_a).run()
    assert app_a.completed_count == 1

    app_b = MockApp()
    ArchiveWorker(str(segundo), str(destino), app_b).run()

    assert app_b.completed_count == 1
    assert any("CONFLICTO" in msg for msg in app_b.log)

    # El primero no fue sobrescrito y el segundo si llego al deposito.
    assert (destino / "Pieza_001" / "IMG.CR2").read_bytes() == b"PRIMERO"

    nombres = os.listdir(destino)
    duplicadas = [n for n in nombres if n.startswith("Pieza_001__")]

    assert len(duplicadas) == 1
    copiado = destino / duplicadas[0] / "IMG.CR2"
    assert copiado.read_bytes() == b"SEGUNDO"


def test_archivo_final_es_idempotente_para_la_misma_sesion(ssd_por_pieza, tmp_path):
    adopt_root(str(ssd_por_pieza), operator="Victor")
    destino = tmp_path / "Deposito"

    primera = MockApp()
    ArchiveWorker(str(ssd_por_pieza), str(destino), primera).run()

    segunda = MockApp()
    ArchiveWorker(str(ssd_por_pieza), str(destino), segunda).run()

    assert segunda.completed_count == 2
    assert not any("CONFLICTO" in msg for msg in segunda.log)
    assert len([n for n in os.listdir(destino) if n.startswith("Pieza_001")]) == 1
