import os
import json
import sys
import pytest

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from lib_archive import ArchiveWorker
from lib_copy import secure_copy

# Mock App for callbacks
class MockApp:
    def __init__(self):
        self.log = []
        self.status = ""
        self.progress_val = 0
        self.progress_msg = ""
        self.failed_err = None
        self.completed_count = 0

    def log_message(self, msg):
        self.log.append(msg)

    def update_archive_status(self, msg):
        self.status = msg

    def update_archive_progress(self, val, msg):
        self.progress_val = val
        self.progress_msg = msg

    def archive_complete(self, count):
        self.completed_count = count

    def archive_failed(self, err):
        self.failed_err = err

@pytest.fixture
def workspace(tmp_path):
    # Setup: External Drive (Src) and Final Storage (Dest)
    src = tmp_path / "External"
    dest = tmp_path / "Final"
    
    # Structure
    backup_ingest = src / "Backup_Ingesta"
    backup_ingest.mkdir(parents=True)
    
    return src, dest, backup_ingest

def test_archive_success(workspace):
    src, dest, backup_ingest = workspace
    
    # Create a session
    session_dir = backup_ingest / "Session_001"
    session_dir.mkdir()
    
    # Create a file
    file1 = session_dir / "image1.jpg"
    file1.write_bytes(b"DATA1")
    
    # Calculate hash manually or via helper
    hash1 = secure_copy(str(file1), str(file1) + ".tmp") # Hack to get hash easily
    os.remove(str(file1) + ".tmp")
    
    # Create Manifest
    manifest = {
        "files": [
            {"path": "image1.jpg", "hash": hash1, "size": 5}
        ]
    }
    (session_dir / "manifest.json").write_text(json.dumps(manifest))

    # Run Worker
    app = MockApp()
    worker = ArchiveWorker(str(src), str(dest), app)
    worker.run() # Run synchronously for test

    # Verify
    assert app.completed_count == 1
    assert (dest / "Session_001" / "image1.jpg").exists()
    assert (dest / "Session_001" / "audit_log.txt").exists()
    assert (dest / "Session_001" / "manifest.json").exists()

def test_archive_integrity_failure(workspace):
    src, dest, backup_ingest = workspace
    
    # Create corrupted session
    session_dir = backup_ingest / "Session_Corrupt"
    session_dir.mkdir()
    
    file1 = session_dir / "bad.jpg"
    file1.write_bytes(b"CORRUPT_DATA") # Actual logic
    
    # Manifest expects "GOOD_DATA" hash
    # GOOD_DATA hash (BLAKE3 of b"GOOD_DATA")
    # Using a known hash or just random string to force mismatch
    expected_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    
    manifest = {
        "files": [
            {"path": "bad.jpg", "hash": expected_hash, "size": 10}
        ]
    }
    (session_dir / "manifest.json").write_text(json.dumps(manifest))

    # Run Worker
    app = MockApp()
    worker = ArchiveWorker(str(src), str(dest), app)
    worker.run()

    # Verify
    assert app.completed_count == 0 # Should count as failed session
    # Log should contain CRITICAL
    assert any("INTEGRITY ERROR" in msg for msg in app.log)
    # File might exist (copied) but audit log should NOT exist or indicate failure
    assert not (dest / "Session_Corrupt" / "audit_log.txt").exists()
