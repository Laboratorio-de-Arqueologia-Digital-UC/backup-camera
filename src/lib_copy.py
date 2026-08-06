import os
import blake3
import logging


def secure_copy(src, dst, callback_progress=None):
    """
    Copies a file from src to dst while calculating its BLAKE3 hash.

    Args:
        src (str): Source file path.
        dst (str): Destination file path.
        callback_progress (callable): Function(bytes_written, total_size) called during copy.

    Returns:
        str: The hexadecimal BLAKE3 hash of the file.

    Raises:
        IOError: If copy fails.
    """
    hasher = blake3.blake3()
    buffer_size = 1024 * 1024  # 1MB

    total_size = os.path.getsize(src)
    copied = 0

    # Ensure directory exists
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    try:
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while True:
                chunk = fsrc.read(buffer_size)
                if not chunk:
                    break

                fdst.write(chunk)
                hasher.update(chunk)

                copied += len(chunk)
                if callback_progress:
                    callback_progress(copied, total_size)

        return hasher.hexdigest()

    except Exception as e:
        # Cleanup on failure to avoid partial corrupted files
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        raise IOError(f"Failed to copy {src} to {dst}: {e}")


def hash_file(file_path, callback_progress=None):
    """
    Calculates the BLAKE3 hash of an existing file, without copying it.

    Used to build a retroactive integrity baseline over data that was already
    copied outside the system (see lib_adopt). Note this is different from
    scripts/generate_blake3_hashes.py, which only re-derives the flat hash map
    from an existing manifest and never reads the actual file bytes.

    Args:
        file_path (str): File to hash.
        callback_progress (callable): Function(bytes_read, total_size).

    Returns:
        str: The hexadecimal BLAKE3 hash of the file.
    """
    hasher = blake3.blake3()
    buffer_size = 1024 * 1024  # 1MB

    total_size = os.path.getsize(file_path)
    read = 0

    with open(file_path, "rb") as handle:
        while True:
            chunk = handle.read(buffer_size)
            if not chunk:
                break
            hasher.update(chunk)
            read += len(chunk)
            if callback_progress:
                callback_progress(read, total_size)

    return hasher.hexdigest()


def verify_hash(file_path, expected_hash):
    """
    Recalculates hash of a file and compares with expected_hash.
    """
    try:
        return hash_file(file_path) == expected_hash
    except Exception as e:
        logging.error(f"Error verifying hash for {file_path}: {e}")
        return False
