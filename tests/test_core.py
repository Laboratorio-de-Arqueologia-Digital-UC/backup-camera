import os
import sys
import pytest
import tempfile
import shutil
import hashlib

# Add src to path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from lib_storage import calculate_required_space, generate_folder_name
from lib_copy import secure_copy, verify_hash

@pytest.fixture
def temp_env():
    # Create a temp directory structure
    with tempfile.TemporaryDirectory() as temp_dir:
        src = os.path.join(temp_dir, "src")
        dst = os.path.join(temp_dir, "dst")
        os.makedirs(src)
        os.makedirs(dst)
        yield src, dst

def test_secure_copy_integrity(temp_env):
    src_dir, dst_dir = temp_env
    
    # Create a dummy file
    src_file = os.path.join(src_dir, "test.bin")
    data = b"Hello, Forensics!" * 1024
    with open(src_file, "wb") as f:
        f.write(data)
        
    dst_file = os.path.join(dst_dir, "test.bin")
    
    # Run secure copy
    computed_hash = secure_copy(src_file, dst_file)
    
    # Verify file content
    assert os.path.exists(dst_file)
    with open(dst_file, "rb") as f:
        copied_data = f.read()
    assert copied_data == data
    
    # Verify Hash using blake3 manually or via lib
    # Since we can't easily install blake3 in this test env if not present (but we added it),
    # let's assume secure_copy returns the hash.
    # We'll use verify_hash from lib_copy
    
    assert verify_hash(dst_file, computed_hash) == True

def test_storage_calculation(temp_env):
    src_dir, _ = temp_env
    
    # Create multiple files
    f1 = os.path.join(src_dir, "1.txt")
    with open(f1, "w") as f: f.write("A" * 100) # 100 bytes
    
    f2 = os.path.join(src_dir, "2.txt")
    with open(f2, "w") as f: f.write("B" * 200) # 200 bytes
    
    sub = os.path.join(src_dir, "sub")
    os.makedirs(sub)
    f3 = os.path.join(sub, "3.txt")
    with open(f3, "w") as f: f.write("C" * 300) # 300 bytes
    
    total = calculate_required_space(src_dir)
    assert total == 600

def test_folder_naming():
    # Test format: YYYY-MM-DD_SD-Serial_HHMM
    name = generate_folder_name("123-ABC", "C:\\")
    assert "SD-123-ABC" in name
    assert len(name.split("_")) >= 3
