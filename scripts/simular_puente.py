import os
import sys
from unittest.mock import patch

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from lib_bridge import BridgeWorker


class MockApp:
    def __init__(self):
        self.status = []
        self.progress = []
        self.failed = False
        self.complete = False
        self.error_msg = ""
        self.complete_path = ""

    def update_status(self, msg):
        print(f"[STATUS] {msg}")
        self.status.append(msg)

    def update_progress(self, val, msg):
        pass  # print(f"[PROGRESS] {val*100:.1f}% - {msg}")

    def ingest_failed(self, msg):
        print(f"[FAILED] {msg}")
        self.failed = True
        self.error_msg = msg

    def ingest_complete(self, path):
        print(f"[COMPLETE] {path}")
        self.complete = True
        self.complete_path = path


def run_simulation(test_name, total_sd_gb, free_int_gb, free_ext_gb):
    print(f"\n{'=' * 50}")
    print(f"SIMULATION: {test_name}")
    print(f"SD Size: {total_sd_gb} GB")
    print(f"Internal Free Space: {free_int_gb} GB")
    print(f"External Free Space: {free_ext_gb} GB")
    print(f"{'=' * 50}")

    app = MockApp()

    src = "SIM_SD"
    internal = "SIM_INT"
    external = "SIM_EXT"

    os.makedirs(src, exist_ok=True)
    os.makedirs(internal, exist_ok=True)
    os.makedirs(external, exist_ok=True)

    # Generate mock file list in SD
    file_list = []
    file_size = 1 * 1024**3  # 1GB files
    num_files = int(total_sd_gb)

    # We will mock os.walk and os.path.getsize
    for i in range(num_files):
        fname = f"file_{i}.mp4"
        file_list.append(fname)

    def mock_walk(path):
        if path == src:
            yield src, [], file_list
        else:
            yield path, [], []

    def mock_getsize(path):
        if "SIM_SD" in path and path.endswith(".mp4"):
            return file_size
        return 0

    def mock_secure_copy(s, d):
        # Just simulate hash return
        return "mock_hash_123"

    def mock_disk_usage(path):
        if path == external:
            return (
                free_ext_gb * 1024**3 * 2,
                free_ext_gb * 1024**3,
                free_ext_gb * 1024**3,
            )
        if path == internal:
            return (
                free_int_gb * 1024**3 * 2,
                free_int_gb * 1024**3,
                free_int_gb * 1024**3,
            )
        return (1000, 1000, 1000)

    with (
        patch("os.walk", side_effect=mock_walk),
        patch("os.path.getsize", side_effect=mock_getsize),
        patch("shutil.disk_usage", side_effect=mock_disk_usage),
        patch("lib_bridge.secure_copy", side_effect=mock_secure_copy),
        patch("lib_bridge.save_hashes_blake3", return_value=None),
        patch("os.makedirs"),
        patch("shutil.rmtree"),
        patch("shutil.move"),
        patch("os.remove"),
    ):
        # write a dummy manifest open to not fail
        from io import StringIO

        with patch("builtins.open", return_value=StringIO()):
            worker = BridgeWorker(src, internal, external, app)
            worker.run()

    print(f"Completed: {app.complete}, Failed: {app.failed}")
    if app.failed:
        print(f"Error: {app.error_msg}")


if __name__ == "__main__":
    # Case 1: Enough External, Enough Internal for full copy
    run_simulation(
        "Sufficient Space (Full Persist)",
        total_sd_gb=20,
        free_int_gb=50,
        free_ext_gb=100,
    )

    # Case 2: Enough External, Internal space tight (chunking required)
    # Bridge chunk logic uses chunk_target = 5GB + 2GB safety buffer = needs at least ~7GB for small chunks
    # Let's say we have 10GB free internal, we need to move 20GB.
    run_simulation(
        "Limited Internal Space (Chunked bridging)",
        total_sd_gb=20,
        free_int_gb=10,
        free_ext_gb=100,
    )

    # Case 3: Very limited Internal Space (Not enough for 1 file + safety buffer)
    # Safety buffer is 2GB. Max free space is 2.5GB. Available = 0.5 GB. Files are 1GB. It should fail or chunk tiny?
    run_simulation(
        "Critically Low Internal Space",
        total_sd_gb=20,
        free_int_gb=2.5,
        free_ext_gb=100,
    )

    # Case 4: Not enough External Space
    run_simulation(
        "Insufficient External Space", total_sd_gb=20, free_int_gb=50, free_ext_gb=10
    )
