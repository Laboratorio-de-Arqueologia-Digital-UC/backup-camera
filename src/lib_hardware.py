import wmi
import logging


def get_real_hardware_id(drive_letter):
    """
    Identifies the unique hardware Serial Number of the physical disk backing a given drive letter.
    Now supports any interface (USB, PCIe, SCSI) by traversing up from LogicalDisk.

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
        # 1. Start from the specific Logical Disk (Letter) we are interested in.
        # This is strictly more efficient and correct than iterating all drives.
        logical_disks = c.Win32_LogicalDisk(DeviceID=drive_letter)

        if not logical_disks:
            logging.warning(f"Drive {drive_letter} not found provided WMI.")
            return None

        logical_disk = logical_disks[0]

        # 2. Traverse UP to Partition
        for partition in logical_disk.associators("Win32_LogicalDiskToPartition"):
            # 3. Traverse UP to Physical Disk
            for physical_disk in partition.associators(
                "Win32_DiskDriveToDiskPartition"
            ):
                # We found the physical backing!
                serial = (
                    physical_disk.SerialNumber.strip()
                    if physical_disk.SerialNumber
                    else "UNKNOWN_SERIAL"
                )
                model = physical_disk.Model
                logging.info(
                    f"Resolved {drive_letter} -> Model: {model}, Serial: {serial}"
                )
                return serial

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
    Returns a list of available removable media with their letters and hardware IDs.
    Supports USB and other removable interfaces (SD cards via PCIe).
    """
    drives = []
    try:
        c = wmi.WMI()
        # Query ALL physical drives, then filter.
        # This ensures we catch SD cards that might show up as specialized SCSI or other interfaces.
        # We rely on 'MediaType' or 'InterfaceType'.

        for physical_disk in c.Win32_DiskDrive():
            # Filter criteria:
            # 1. Interface is USB
            # 2. OR MediaType indicates removable (e.g. "Removable Media", "External hard disk media")
            # Note: Checking "Removable" in MediaType is robust for SD cards.

            is_usb = (
                "USB" in physical_disk.InterfaceType.upper()
                if physical_disk.InterfaceType
                else False
            )
            is_removable = (
                physical_disk.MediaType
                and "REMOVABLE" in physical_disk.MediaType.upper()
            )

            # Skip if neither (likely internal fixed disk)
            if not (is_usb or is_removable):
                continue

            serial = (
                physical_disk.SerialNumber.strip()
                if physical_disk.SerialNumber
                else "UNKNOWN"
            )
            model = physical_disk.Model

            # Simple card type heuristics
            card_type = "USB Drive"
            model_upper = model.upper() if model else ""
            if "SD" in model_upper or "SDXC" in model_upper:
                card_type = "SD Card"
            elif "MICRO" in model_upper:
                card_type = "MicroSD"

            # Traverse DOWN to find the Letter(s)
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
                            "type": card_type,
                        }
                    )
    except Exception as e:
        logging.error(f"Error scanning drives: {e}")

    return drives
