import wmi
import logging


def get_real_hardware_id(drive_letter):
    """
    Identifies the unique hardware Serial Number of the physical disk backing a given drive letter.

    Args:
        drive_letter (str): Drive letter, e.g., "F:" or "F"

    Returns:
        str or None: The stripped SerialNumber of the physical media, or None if not found.
    """
    # Ensure drive letter has colon
    drive_letter = drive_letter.upper()
    if not drive_letter.endswith(":"):
        drive_letter += ":"

    try:
        c = wmi.WMI()
        # 1. Find the logical disk (partition-like view for OS logic)
        # Note: We traverse up: LogicalDisk -> Partition -> DiskDrive

        # Performance optimization: Query specific logical disk first if possible,
        # but WMI associations are often easier to traverse from DiskDrive down or just iterating.
        # Given the requirements, let's look for USB drives first as that's the use case.

        for physical_disk in c.Win32_DiskDrive(InterfaceType="USB"):
            # 2. Find partitions associated with this physical disk
            for partition in physical_disk.associators(
                "Win32_DiskDriveToDiskPartition"
            ):
                # 3. Find logical disks associated with this partition
                for logical_disk in partition.associators(
                    "Win32_LogicalDiskToPartition"
                ):
                    if logical_disk.DeviceID == drive_letter:
                        # Found the drive! Return the physical SerialNumber.
                        return physical_disk.SerialNumber.strip()

    except Exception as e:
        logging.error(f"Error accessing WMI for drive {drive_letter}: {e}")
        return None

    return None


def get_drive_info(drive_letter):
    """
    Returns basic info about the drive (Volume Name, Free Space, Total Size).
    """
    drive_letter = drive_letter.upper()
    if not drive_letter.endswith(":"):
        drive_letter += ":"

    try:
        c = wmi.WMI()
        for disk in c.Win32_LogicalDisk(DeviceID=drive_letter):
            return {
                "label": disk.VolumeName or "NO_LABEL",
                "free": int(disk.FreeSpace) if disk.FreeSpace else 0,
                "size": int(disk.Size) if disk.Size else 0,
                "filesystem": disk.FileSystem,
            }
    except Exception as e:
        logging.error(f"Error getting info for {drive_letter}: {e}")
        return None
    return None


def scan_drives():
    """
    Returns a list of available removable/USB drives with their letters and hardware IDs.
    """
    drives = []
    try:
        c = wmi.WMI()
        # Iterate over physical USB drives to get the chain of trust
        for physical_disk in c.Win32_DiskDrive(InterfaceType="USB"):
            serial = physical_disk.SerialNumber.strip()
            model = physical_disk.Model

            for partition in physical_disk.associators(
                "Win32_DiskDriveToDiskPartition"
            ):
                for logical_disk in partition.associators(
                    "Win32_LogicalDiskToPartition"
                ):
                    drives.append(
                        {
                            "letter": logical_disk.DeviceID,
                            "serial": serial,
                            "model": model,
                            "label": logical_disk.VolumeName or "NO_LABEL",
                        }
                    )
    except Exception as e:
        logging.error(f"Error scanning drives: {e}")

    return drives
