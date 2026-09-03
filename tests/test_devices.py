import json
import unittest
from unittest import mock

from bootcrafter_linux.devices import Device, parse_lsblk, validate_target_device


class DeviceTests(unittest.TestCase):
    def test_filters_internal_readonly_and_system_disk(self):
        payload = json.dumps({"blockdevices": [
            {"path": "/dev/sda", "type": "disk", "size": 500000000000, "tran": "sata", "rm": False, "hotplug": False, "ro": False,
             "children": [{"path": "/dev/sda1", "type": "part", "mountpoints": ["/"]}]},
            {"path": "/dev/sdb", "type": "disk", "size": 32000000000, "tran": "usb", "rm": True, "hotplug": True, "ro": False, "model": "Flash"},
            {"path": "/dev/sdc", "type": "disk", "size": 64000000000, "tran": "usb", "rm": True, "hotplug": True, "ro": True},
        ]})
        devices = parse_lsblk(payload)
        self.assertEqual([d.path for d in devices], ["/dev/sdb"])

    def test_live_media_and_swap_are_protected(self):
        payload = json.dumps({"blockdevices": [
            {"path": "/dev/sdb", "type": "disk", "size": 100, "tran": "usb", "rm": True, "hotplug": True, "ro": False,
             "children": [{"path": "/dev/sdb1", "type": "part", "mountpoints": ["/run/live/medium"]}]},
            {"path": "/dev/sdc", "type": "disk", "size": 100, "tran": "usb", "rm": True, "hotplug": True, "ro": False,
             "children": [{"path": "/dev/sdc1", "type": "part", "mountpoints": ["[SWAP]"]}]},
        ]})
        self.assertEqual(parse_lsblk(payload), [])

    def test_usb_system_disk_is_still_blocked(self):
        payload = json.dumps({"blockdevices": [
            {"path": "/dev/sda", "type": "disk", "size": 100, "tran": "usb", "rm": True, "hotplug": True, "ro": False,
             "children": [{"path": "/dev/sda2", "type": "part", "mountpoints": ["/boot/efi"]}]},
        ]})
        self.assertEqual(parse_lsblk(payload), [])

    def test_system_data_mounts_are_protected_but_media_mounts_are_allowed(self):
        payload = json.dumps({"blockdevices": [
            {"path": "/dev/sdb", "type": "disk", "size": 100, "tran": "usb", "rm": True, "hotplug": True, "ro": False,
             "children": [{"path": "/dev/sdb1", "type": "part", "mountpoints": ["/home"]}]},
            {"path": "/dev/sdc", "type": "disk", "size": 100, "tran": "usb", "rm": True, "hotplug": True, "ro": False,
             "children": [{"path": "/dev/sdc1", "type": "part", "mountpoints": ["/media/user/USB"]}]},
        ]})
        self.assertEqual([d.path for d in parse_lsblk(payload)], ["/dev/sdc"])

    def test_identity_is_path_bound_for_identical_serialless_drives(self):
        a = Device("/dev/sdb", 100, "Flash", "Vendor", "usb", True, True, False, False)
        b = Device("/dev/sdc", 100, "Flash", "Vendor", "usb", True, True, False, False)
        self.assertNotEqual(a.identity_token, b.identity_token)

    def test_identity_token_changes_with_device_identity(self):
        a = Device("/dev/sdb", 100, "Flash", "Vendor", "usb", True, True, False, False, "ABC")
        b = Device("/dev/sdb", 101, "Flash", "Vendor", "usb", True, True, False, False, "ABC")
        self.assertNotEqual(a.identity_token, b.identity_token)

    @mock.patch("bootcrafter_linux.devices.lsblk_json")
    def test_validate_target_rejects_identity_mismatch(self, lsblk):
        lsblk.return_value = json.dumps({"blockdevices": [
            {"path": "/dev/sdb", "type": "disk", "size": 32000000000, "tran": "usb", "rm": True,
             "hotplug": True, "ro": False, "model": "Flash", "vendor": "Vendor", "serial": "A"}
        ]})
        with self.assertRaisesRegex(ValueError, "changed after selection"):
            validate_target_device("/dev/sdb", "not-the-current-token")


if __name__ == "__main__":
    unittest.main()
