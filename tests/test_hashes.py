import os
import json
import sys
import pytest
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from lib_storage import save_hashes_blake3

def test_save_hashes_blake3_format():
    with tempfile.TemporaryDirectory() as tmp:
        session_path = Path(tmp)
        files = [
            {"path": "DCIM/IMG_001.JPG", "hash": "hash123", "size": 100},
            {"path": "MISC/TRACK.LOG", "hash": "abc456", "size": 50},
        ]
        
        output_path = save_hashes_blake3(str(session_path), files)
        
        assert os.path.exists(output_path)
        assert os.path.basename(output_path) == "hashes_blake3.json"
        
        with open(output_path, "r") as f:
            data = json.load(f)
        
        # Check format: Flat dictionary {basename: hash}
        assert isinstance(data, dict)
        assert len(data) == 2
        assert data["IMG_001.JPG"] == "hash123"
        assert data["TRACK.LOG"] == "abc456"
        # Ensure it does NOT use full paths as keys
        assert "DCIM/IMG_001.JPG" not in data

def test_save_hashes_blake3_overwrite():
    with tempfile.TemporaryDirectory() as tmp:
        session_path = Path(tmp)
        hashes_path = session_path / "hashes_blake3.json"
        
        # Pre-create with dummy data
        with open(hashes_path, "w") as f:
            f.write("{}")
            
        files = [{"path": "new.jpg", "hash": "newhash", "size": 1}]
        save_hashes_blake3(str(session_path), files)
        
        with open(hashes_path, "r") as f:
            data = json.load(f)
            
        assert data["new.jpg"] == "newhash"

if __name__ == "__main__":
    pytest.main([__file__])
