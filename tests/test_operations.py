import bz2
import gzip
import hashlib
import lzma
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from bootcrafter_linux.devices import Device
from bootcrafter_linux.operations import (
    _copy_windows_tree,
    _scan_windows_tree,
    format_drive,
    has_uefi_boot_file,
    image_stream,
    partition_path,
    partition_script,
    sanitize_label,
    sha256_file,
    validate_windows_source_tree,
    windows_payload_bytes,
    write_image,
    make_windows_usb,
)


class OperationTests(unittest.TestCase):
    def test_sha256_file(self):
        payload = b"bootcrafter-test" * 1000
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(payload)
            path = f.name
        try:
            self.assertEqual(sha256_file(path), hashlib.sha256(payload).hexdigest())
        finally:
            os.unlink(path)

    def test_compressed_streams(self):
        payload = b"boot-image-data" * 4096
        compressors = [(".gz", gzip.open), (".xz", lzma.open), (".bz2", bz2.open)]
        for suffix, opener in compressors:
            with self.subTest(suffix=suffix):
                fd, path = tempfile.mkstemp(suffix=suffix)
                os.close(fd)
                try:
                    with opener(path, "wb") as f:
                        f.write(payload)
                    stream, total, kind = image_stream(path)
                    with stream:
                        self.assertEqual(stream.read(), payload)
                    self.assertIsNone(total)
                    self.assertTrue(kind)
                finally:
                    os.unlink(path)

    def test_zip_single_image_stream(self):
        payload = b"image" * 10000
        fd, path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr("nested/system.img", payload)
            stream, total, kind = image_stream(path)
            with stream:
                self.assertEqual(stream.read(), payload)
            self.assertEqual(total, len(payload))
            self.assertEqual(kind, "zip")
        finally:
            os.unlink(path)

    def test_zip_rejects_ambiguous_images(self):
        fd, path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        try:
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("a.img", b"a")
                z.writestr("b.iso", b"b")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                image_stream(path)
        finally:
            os.unlink(path)

    @mock.patch("bootcrafter_linux.operations._clear_stale_target_tail")
    @mock.patch("bootcrafter_linux.operations.unmount_device")
    @mock.patch("bootcrafter_linux.operations.ensure_source_not_on_target")
    @mock.patch("bootcrafter_linux.operations._check_block_device")
    @mock.patch("bootcrafter_linux.operations.require_root")
    @mock.patch("bootcrafter_linux.operations.validate_target_device")
    def test_corrupt_compressed_source_fails_before_target_open(
        self, validate, _root, _block, _source_guard, _unmount, clear_tail
    ):
        with tempfile.NamedTemporaryFile(suffix=".gz", delete=False) as src, tempfile.NamedTemporaryFile(delete=False) as dst:
            src.write(b"not-a-gzip-stream")
            source_path, target_path = src.name, dst.name
        device = Device(target_path, 64 * 1024 * 1024, "USB", "V", "usb", True, True, False, False, "SER")
        validate.return_value = device
        try:
            with self.assertRaises((gzip.BadGzipFile, OSError)):
                write_image(source_path, target_path, expected_identity=device.identity_token)
            clear_tail.assert_not_called()
        finally:
            os.unlink(source_path)
            os.unlink(target_path)

    @mock.patch("bootcrafter_linux.operations._reread_partitions")
    @mock.patch("bootcrafter_linux.operations._flush_target")
    @mock.patch("bootcrafter_linux.operations.unmount_device")
    @mock.patch("bootcrafter_linux.operations.ensure_source_not_on_target")
    @mock.patch("bootcrafter_linux.operations._check_block_device")
    @mock.patch("bootcrafter_linux.operations.require_root")
    @mock.patch("bootcrafter_linux.operations.validate_target_device")
    def test_raw_write_and_verify_pipeline(self, validate, _root, _block, _source_guard, _unmount, _flush, _reread):
        payload = (b"BOOTCRAFT-RAW-IMAGE" * 4096) + b"end"
        target_size = 40 * 1024 * 1024
        with tempfile.NamedTemporaryFile(delete=False) as src, tempfile.NamedTemporaryFile(delete=False) as dst:
            src.write(payload)
            source_path = src.name
            target_path = dst.name
            dst.truncate(target_size)
            dst.seek(target_size - 4096)
            dst.write(b"X" * 4096)
        device = Device(target_path, target_size, "Test USB", "Test", "usb", True, True, False, False, "SERIAL")
        validate.return_value = device
        events = []
        try:
            write_image(
                source_path,
                target_path,
                verify=True,
                expected_identity=device.identity_token,
                progress=lambda event, **data: events.append((event, data)),
            )
            with open(target_path, "rb") as f:
                self.assertEqual(f.read(len(payload)), payload)
                f.seek(target_size - 4096)
                self.assertEqual(f.read(4096), b"\0" * 4096)
            self.assertTrue(any(event == "verified" for event, _ in events))
            self.assertTrue(any(event == "done" for event, _ in events))
            validate.assert_called_with(target_path, device.identity_token)
        finally:
            os.unlink(source_path)
            os.unlink(target_path)

    def test_partition_paths(self):
        self.assertEqual(partition_path("/dev/sdb"), "/dev/sdb1")
        self.assertEqual(partition_path("/dev/nvme0n1"), "/dev/nvme0n1p1")
        self.assertEqual(partition_path("/dev/mmcblk0"), "/dev/mmcblk0p1")

    def test_label_sanitizing(self):
        self.assertEqual(sanitize_label("my:usb/name", "fat32"), "MYUSBNAME")
        self.assertLessEqual(len(sanitize_label("x" * 99, "ext4")), 16)
        self.assertEqual(sanitize_label("", "fat32"), "BOOTCRAFT")
        self.assertEqual(sanitize_label("MY PROXMOX USB", "fat32"), "MY PROXMOX")
        self.assertEqual(sanitize_label("USB😀:TEST", "fat32"), "USBTEST")
        self.assertLessEqual(len(sanitize_label("😀" * 20, "ext4").encode("utf-8")), 16)

    def test_partition_scripts_use_compatible_types(self):
        self.assertIn(",,c", partition_script("mbr", "fat32"))
        self.assertIn(",,7", partition_script("mbr", "ntfs"))
        self.assertIn(",,83", partition_script("mbr", "ext4"))
        self.assertIn(",,c,*", partition_script("mbr", "fat32", bootable=True))
        self.assertIn("EBD0A0A2", partition_script("gpt", "fat32"))
        self.assertIn("0FC63DAF", partition_script("gpt", "ext4"))

    def test_windows_payload_counts_split_wim_source(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"w" * 1234)
            path = f.name
        try:
            scan = ([], (path, "sources/install.swm"), 5000)
            self.assertEqual(windows_payload_bytes(scan), 6234)
        finally:
            os.unlink(path)

    @mock.patch("bootcrafter_linux.operations.unmount_device")
    @mock.patch("bootcrafter_linux.operations.require_command")
    @mock.patch("bootcrafter_linux.operations.validate_target_device")
    @mock.patch("bootcrafter_linux.operations._check_block_device")
    @mock.patch("bootcrafter_linux.operations.require_root")
    def test_format_checks_formatter_before_unmount(self, _root, _block, validate, require, unmount):
        with tempfile.NamedTemporaryFile(delete=False) as target:
            target_path = target.name
        validate.return_value = Device(target_path, 64 * 1024 * 1024, "USB", "V", "usb", True, True, False, False, "S")
        def fake_require(name):
            if name == "mkfs.vfat":
                raise RuntimeError("missing formatter")
            return f"/usr/bin/{name}"
        require.side_effect = fake_require
        try:
            with self.assertRaisesRegex(RuntimeError, "missing formatter"):
                format_drive(target_path, "gpt", "fat32", "TEST")
            unmount.assert_not_called()
        finally:
            os.unlink(target_path)

    @mock.patch("bootcrafter_linux.operations._run")
    @mock.patch("bootcrafter_linux.operations.unmount_device")
    @mock.patch("bootcrafter_linux.operations.validate_windows_source_tree")
    @mock.patch("bootcrafter_linux.operations.require_command", side_effect=lambda name: f"/usr/bin/{name}")
    @mock.patch("bootcrafter_linux.operations.ensure_source_not_on_target")
    @mock.patch("bootcrafter_linux.operations.validate_target_device")
    @mock.patch("bootcrafter_linux.operations._check_block_device")
    @mock.patch("bootcrafter_linux.operations.require_root")
    def test_windows_capacity_fails_before_target_unmount(
        self, _root, _block, validate, _guard, _require, validate_tree, unmount, _run
    ):
        with tempfile.NamedTemporaryFile(suffix=".iso", delete=False) as src, tempfile.NamedTemporaryFile(delete=False) as dst:
            src.write(b"iso")
            source_path, target_path = src.name, dst.name
        validate.return_value = Device(target_path, 96 * 1024 * 1024, "USB", "V", "usb", True, True, False, False, "S")
        validate_tree.return_value = ([], None, 128 * 1024 * 1024)
        try:
            with self.assertRaisesRegex(ValueError, "too small"):
                make_windows_usb(source_path, target_path)
            unmount.assert_not_called()
        finally:
            os.unlink(source_path)
            os.unlink(target_path)

    def _make_windows_tree(self, root: str):
        os.makedirs(os.path.join(root, "EFI", "BOOT"))
        os.makedirs(os.path.join(root, "sources"))
        with open(os.path.join(root, "EFI", "BOOT", "BOOTX64.EFI"), "wb") as f:
            f.write(b"efi")
        with open(os.path.join(root, "sources", "boot.wim"), "wb") as f:
            f.write(b"bootwim")
        with open(os.path.join(root, "setup.exe"), "wb") as f:
            f.write(b"setup")

    def test_windows_tree_validation_and_copy(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            self._make_windows_tree(src)
            self.assertTrue(has_uefi_boot_file(src))
            scan = validate_windows_source_tree(src)
            events = []
            _copy_windows_tree(src, dst, lambda event, **data: events.append((event, data)), scan=scan)
            with open(os.path.join(dst, "EFI", "BOOT", "BOOTX64.EFI"), "rb") as f:
                self.assertEqual(f.read(), b"efi")
            self.assertTrue(any(event == "progress" for event, _ in events))

    def test_windows_validation_rejects_non_installer_before_write(self):
        with tempfile.TemporaryDirectory() as src:
            os.makedirs(os.path.join(src, "EFI", "BOOT"))
            with open(os.path.join(src, "EFI", "BOOT", "BOOTX64.EFI"), "wb") as f:
                f.write(b"efi")
            with self.assertRaisesRegex(ValueError, "boot.wim"):
                validate_windows_source_tree(src)

    def test_windows_tree_rejects_arbitrary_oversize_file(self):
        with tempfile.TemporaryDirectory() as src:
            self._make_windows_tree(src)
            huge = os.path.join(src, "huge.bin")
            with open(huge, "wb") as f:
                f.truncate(4 * 1024 * 1024 * 1024)
            with self.assertRaisesRegex(ValueError, "larger than 4 GiB"):
                _scan_windows_tree(src)

    @mock.patch("bootcrafter_linux.operations.shutil.which")
    def test_windows_big_wim_requires_wimlib(self, which):
        def fake_which(name):
            if name == "wimlib-imagex":
                return None
            return f"/usr/bin/{name}"
        which.side_effect = fake_which
        with tempfile.TemporaryDirectory() as src:
            self._make_windows_tree(src)
            install = os.path.join(src, "sources", "install.wim")
            with open(install, "wb") as f:
                f.truncate(4 * 1024 * 1024 * 1024)
            with self.assertRaisesRegex(RuntimeError, "wimtools"):
                validate_windows_source_tree(src)


if __name__ == "__main__":
    unittest.main()
