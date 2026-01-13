import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock wmi module before importing lib_hardware
sys.modules['wmi'] = MagicMock()

# Now import the library to test
from src import lib_hardware  # noqa: E402

class TestHardwareDetection(unittest.TestCase):
    
    @patch('wmi.WMI')
    def test_scan_drives(self, mock_wmi_cls):
        # Setup Mock Data
        mock_wmi = MagicMock()
        mock_wmi_cls.return_value = mock_wmi
        
        # 1. USB Pen Drive (Standard)
        usb_disk = MagicMock()
        usb_disk.InterfaceType = "USB"
        usb_disk.MediaType = "External hard disk media"
        usb_disk.SerialNumber = "USB123"
        usb_disk.Model = "SanDisk Ultra USB"
        
        # 2. Internal SD Reader (PCIe/SCSI) - The critical test case
        sd_disk = MagicMock()
        sd_disk.InterfaceType = "SCSI" # or IDE, or PCIE
        sd_disk.MediaType = "Removable Media" 
        sd_disk.SerialNumber = "SD456"
        sd_disk.Model = "Generic SD/MMC CR"
        
        # 3. Fixed System Disk (Should be ignored)
        fixed_disk = MagicMock()
        fixed_disk.InterfaceType = "IDE"
        fixed_disk.MediaType = "Fixed hard disk media"
        fixed_disk.SerialNumber = "FIXED789"
        fixed_disk.Model = "Samsung SSD 970 EVO"
        
        mock_wmi.Win32_DiskDrive.return_value = [usb_disk, sd_disk, fixed_disk]
        
        # Setup Associations (Disk -> Partition -> Logical)
        # USB Associates
        usb_part = MagicMock()
        usb_logical = MagicMock()
        usb_logical.DeviceID = "E:"
        usb_logical.VolumeName = "MY_USB"
        
        usb_disk.associators.return_value = [usb_part]
        usb_part.associators.return_value = [usb_logical]

        # SD Associates
        sd_part = MagicMock()
        sd_logical = MagicMock()
        sd_logical.DeviceID = "F:"
        sd_logical.VolumeName = "EOS_DIGITAL"
        
        sd_disk.associators.return_value = [sd_part]
        sd_part.associators.return_value = [sd_logical]
        
        # Fixed Associates (Need to exist so code doesn't crash, but shouldn't be reached ideally if filtered early)
        fixed_disk.associators.return_value = [] 
        
        # ACT
        results = lib_hardware.scan_drives()
        
        # ASSERT
        print("\nDetected Drives:")
        for d in results:
            print(d)
            
        self.assertEqual(len(results), 2, "Should detect exactly 2 drives (USB and SD)")
        
        # Check USB
        usb_res = next(d for d in results if d['serial'] == 'USB123')
        self.assertEqual(usb_res['letter'], 'E:')
        self.assertEqual(usb_res['type'], 'USB Drive')
        
        # Check SD
        sd_res = next(d for d in results if d['serial'] == 'SD456')
        self.assertEqual(sd_res['letter'], 'F:')
        self.assertEqual(sd_res['type'], 'SD Card')

if __name__ == '__main__':
    unittest.main()
