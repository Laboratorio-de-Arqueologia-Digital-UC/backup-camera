import os
import sys
import pytest
from unittest.mock import patch

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from lib_bridge import BridgeWorker


# Mock App Interface
class MockApp:
    def __init__(self):
        self.status = []
        self.progress = []
        self.failed = False
        self.complete = False
        self.error_msg = ""
        self.complete_path = ""

    def update_status(self, msg):
        self.status.append(msg)

    def update_progress(self, val, msg):
        self.progress.append((val, msg))

    def ingest_failed(self, msg):
        self.failed = True
        self.error_msg = msg

    def ingest_complete(self, path):
        self.complete = True
        self.complete_path = path


@pytest.fixture
def mock_env(tmp_path):
    # Setup directories
    src = tmp_path / "SD_CARD"
    internal = tmp_path / "INTERNAL"
    external = tmp_path / "EXTERNAL"

    src.mkdir()
    internal.mkdir()
    external.mkdir()

    # Create some dummy files in SRC
    (src / "DCIM").mkdir()
    with open(src / "DCIM" / "photo1.jpg", "wb") as f:
        f.write(b"DATA1" * 1000)
    with open(src / "DCIM" / "photo2.jpg", "wb") as f:
        f.write(b"DATA2" * 1000)

    return str(src), str(internal), str(external)


def test_bridge_worker_success(mock_env):
    src, internal, external = mock_env
    app = MockApp()

    # Run Worker in Main Thread for testing (skip .start())
    worker = BridgeWorker(src, internal, external, app)
    worker.run()

    assert app.complete
    assert not app.failed

    # Verify External has files
    assert os.path.exists(os.path.join(external, "DCIM", "photo1.jpg"))
    assert os.path.exists(os.path.join(external, "DCIM", "photo2.jpg"))

    # Verify Manifest
    assert os.path.exists(os.path.join(external, "manifest_bridge.json"))

    # Verify Internal Temp is CLEAN
    bridge_temp = os.path.join(internal, "_BRIDGE_TEMP")
    assert not os.path.exists(bridge_temp)


def test_bridge_worker_insufficient_space(mock_env):
    src, internal, external = mock_env
    app = MockApp()

    # Mock disk_usage to return 0 free space on external
    with patch("shutil.disk_usage") as mock_du:
        # Return total, used, free
        # First call might be external or internal depending on implementation order
        # lib_bridge checks external first usually
        def side_effect(path):
            if path == external:
                return (1000, 1000, 0)  # 0 Free
            return (1000000000, 0, 1000000000)

        mock_du.side_effect = side_effect

        worker = BridgeWorker(src, internal, external, app)
        worker.run()

        assert app.failed
        assert (
            "insuficiente" in app.error_msg.lower()
            or "externo" in app.error_msg.lower()
        )
