from __future__ import annotations

import bz2
import gzip
import hashlib
import json
import lzma
import os
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import BinaryIO, Callable

from .devices import lsblk_json, validate_target_device

CHUNK_SIZE = 8 * 1024 * 1024
Progress = Callable[..., None]
SUPPORTED_ZIP_IMAGE_SUFFIXES = (".iso", ".img", ".raw", ".bin")
STALE_TAIL_CLEAR_BYTES = 4 * 1024 * 1024
WINDOWS_FREE_SPACE_MARGIN = 64 * 1024 * 1024


def emit(event: str, **data) -> None:
    print(json.dumps({"event": event, **data}, separators=(",", ":")), flush=True)


def require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("This operation must run as root.")


def command_path(name: str) -> str | None:
    """Find system tools even when a desktop session has a minimal PATH."""
    path = shutil.which(name)
    if path:
        return path
    for directory in ("/usr/sbin", "/usr/bin", "/sbin", "/bin"):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def require_command(name: str) -> str:
    path = command_path(name)
    if not path:
        raise RuntimeError(f"Required command not found: {name}")
    return path


def required_commands(mode: str, filesystem: str | None = None) -> list[str]:
    common = ["lsblk", "findmnt", "umount"]
    if mode == "raw":
        return common
    if mode == "windows":
        return common + ["wipefs", "sfdisk", "mkfs.vfat", "mount", "sync"]
    if mode == "format":
        fs_command = {
            "fat32": "mkfs.vfat",
            "exfat": "mkfs.exfat",
            "ntfs": "mkfs.ntfs",
            "ext4": "mkfs.ext4",
        }.get((filesystem or "").lower())
        return common + ["wipefs", "sfdisk"] + ([fs_command] if fs_command else [])
    return common


def missing_commands(mode: str, filesystem: str | None = None) -> list[str]:
    return [cmd for cmd in required_commands(mode, filesystem) if cmd and not command_path(cmd)]


def _run(argv: list[str], *, input_text: str | None = None) -> str:
    proc = subprocess.run(
        argv,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        output = proc.stdout.strip()
        raise RuntimeError(f"Command failed ({argv[0]}): {output or 'unknown error'}")
    return proc.stdout


def _node_for_device(payload: str, device: str) -> dict | None:
    data = json.loads(payload)
    target = os.path.realpath(device)
    for node in data.get("blockdevices") or []:
        node_path = str(node.get("path") or node.get("name") or "")
        if node_path and os.path.realpath(node_path) == target:
            return node
    return None


def _collect_mountpoints(node: dict) -> list[str]:
    mounts: list[str] = []
    raw = node.get("mountpoints")
    if isinstance(raw, list):
        mounts.extend(str(x) for x in raw if x and str(x).upper() != "[SWAP]")
    elif raw and str(raw).upper() != "[SWAP]":
        mounts.append(str(raw))
    if node.get("mountpoint") and str(node["mountpoint"]).upper() != "[SWAP]":
        mounts.append(str(node["mountpoint"]))
    for child in node.get("children") or []:
        mounts.extend(_collect_mountpoints(child))
    return sorted(set(mounts), key=lambda p: (p.count("/"), len(p)), reverse=True)


def unmount_device(device: str, progress: Progress = emit) -> None:
    node = _node_for_device(lsblk_json(), device)
    if not node:
        raise RuntimeError("Selected drive disappeared.")
    mounts = _collect_mountpoints(node)
    if not mounts:
        return
    umount = require_command("umount")
    for mount in mounts:
        progress("log", message=f"Unmounting {mount}")
        _run([umount, "--", mount])


class _ZipImageStream:
    def __init__(self, archive: zipfile.ZipFile, member: zipfile.ZipExtFile) -> None:
        self.archive = archive
        self.member = member

    def read(self, size: int = -1) -> bytes:
        return self.member.read(size)

    def close(self) -> None:
        try:
            self.member.close()
        finally:
            self.archive.close()

    def __enter__(self) -> "_ZipImageStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class _ProcessImageStream:
    def __init__(self, proc: subprocess.Popen[bytes], stderr_file: BinaryIO) -> None:
        self.proc = proc
        self.stderr_file = stderr_file
        if proc.stdout is None:
            stderr_file.close()
            raise RuntimeError("Compressed image process has no output stream.")
        self.stdout = proc.stdout

    def read(self, size: int = -1) -> bytes:
        return self.stdout.read(size)

    def close(self) -> None:
        error: Exception | None = None
        try:
            self.stdout.close()
            code = self.proc.wait()
            if code != 0:
                self.stderr_file.seek(0)
                stderr = self.stderr_file.read()
                if isinstance(stderr, str):
                    message = stderr
                else:
                    message = stderr.decode(errors="replace")
                error = RuntimeError(f"Compressed image decompression failed: {message.strip() or 'unknown error'}")
        finally:
            self.stderr_file.close()
        if error:
            raise error

    def __enter__(self) -> "_ProcessImageStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Avoid masking an existing exception with a decompressor close error.
        try:
            self.close()
        except Exception:
            if exc_type is None:
                raise


def image_stream(path: str) -> tuple[BinaryIO | _ZipImageStream | _ProcessImageStream, int | None, str]:
    p = Path(path)
    lower = p.name.lower()
    if lower.endswith(".gz"):
        return gzip.open(p, "rb"), None, "gzip"
    if lower.endswith(".xz"):
        return lzma.open(p, "rb"), None, "xz"
    if lower.endswith(".bz2"):
        return bz2.open(p, "rb"), None, "bzip2"
    if lower.endswith(".zip"):
        archive = zipfile.ZipFile(p, "r")
        members = [m for m in archive.infolist() if not m.is_dir()]
        candidates = [m for m in members if m.filename.lower().endswith(SUPPORTED_ZIP_IMAGE_SUFFIXES)]
        if len(candidates) != 1:
            archive.close()
            raise ValueError("ZIP images must contain exactly one ISO/IMG/RAW/BIN file.")
        member = candidates[0]
        return _ZipImageStream(archive, archive.open(member, "r")), member.file_size, "zip"
    if lower.endswith((".zst", ".zstd")):
        zstd = require_command("zstd")
        stderr_file = tempfile.TemporaryFile(mode="w+b")
        try:
            proc = subprocess.Popen([zstd, "-dc", "--", str(p)], stdout=subprocess.PIPE, stderr=stderr_file)
        except Exception:
            stderr_file.close()
            raise
        return _ProcessImageStream(proc, stderr_file), None, "zstd"
    size = p.stat().st_size
    return p.open("rb", buffering=0), size, "raw"


def ensure_source_not_on_target(source: str, target: str) -> None:
    """Refuse to erase a drive that currently stores the selected image file."""
    findmnt = require_command("findmnt")
    lsblk = require_command("lsblk")
    proc = subprocess.run(
        [findmnt, "--target", source, "--noheadings", "--output", "SOURCE"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    backing = proc.stdout.strip().split("[", 1)[0] if proc.returncode == 0 else ""
    if not backing.startswith("/dev/"):
        return
    proc = subprocess.run(
        [lsblk, "--inverse", "--noheadings", "--paths", "--output", "PATH", backing],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    target_real = os.path.realpath(target)
    ancestors = {
        os.path.realpath(line.strip())
        for line in proc.stdout.splitlines()
        if line.strip().startswith("/dev/")
    }
    if target_real in ancestors:
        raise ValueError("The selected image is stored on the target drive. Move the image to another disk first.")


def _check_block_device(path: str) -> None:
    st = os.stat(path)
    if not stat.S_ISBLK(st.st_mode):
        raise ValueError("Target must be a whole block device.")


def _validate_source_file(path: str) -> str:
    source = os.path.realpath(path)
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    if not os.access(source, os.R_OK):
        raise PermissionError(f"Image is not readable: {source}")
    if os.path.getsize(source) <= 0:
        raise ValueError("The selected image file is empty.")
    return source


def _flush_target(target: str) -> None:
    # fsync() happens on the open FD first. blockdev then flushes/invalidate
    # block buffers so verification is less likely to read only cached data.
    blockdev = command_path("blockdev")
    if blockdev:
        subprocess.run([blockdev, "--flushbufs", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _reread_partitions(target: str) -> None:
    partprobe = command_path("partprobe")
    if partprobe:
        subprocess.run([partprobe, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        blockdev = command_path("blockdev")
        if blockdev:
            subprocess.run([blockdev, "--rereadpt", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    udevadm = command_path("udevadm")
    if udevadm:
        subprocess.run([udevadm, "settle", "--timeout=8"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _clear_stale_target_tail(fd: int, target_size: int) -> None:
    """Clear old end-of-disk signatures before a raw image write.

    Raw images overwrite the beginning of a disk, but a larger drive can retain
    an old backup GPT header at its physical end. Clearing a small tail region
    prevents stale metadata from confusing the kernel after the new image is
    written. The image itself never reaches this area unless it fills the drive,
    in which case normal image data overwrites the cleared bytes.
    """
    if target_size <= 0:
        return
    length = min(STALE_TAIL_CLEAR_BYTES, target_size)
    os.lseek(fd, target_size - length, os.SEEK_SET)
    zero = b"\0" * min(CHUNK_SIZE, length)
    remaining = length
    while remaining:
        piece = zero if remaining >= len(zero) else zero[:remaining]
        view = memoryview(piece)
        while view:
            n = os.write(fd, view)
            if n <= 0:
                raise OSError("Short write while clearing stale target metadata.")
            view = view[n:]
        remaining -= len(piece)
    os.lseek(fd, 0, os.SEEK_SET)


def _assert_open_target_matches_path(fd: int, target: str, expected_size: int) -> None:
    """Detect path/capacity replacement between validation and opening."""
    opened = os.fstat(fd)
    current = os.stat(target)
    if stat.S_ISBLK(opened.st_mode):
        if not stat.S_ISBLK(current.st_mode) or opened.st_rdev != current.st_rdev:
            raise RuntimeError("Target device changed while opening it. Refresh and select the USB again.")
    try:
        opened_size = os.lseek(fd, 0, os.SEEK_END)
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError:
        opened_size = expected_size
    if opened_size != expected_size:
        raise RuntimeError("Target drive capacity changed while opening it. Refresh and select the USB again.")


def write_image(
    image: str,
    device: str,
    verify: bool = True,
    expected_identity: str | None = None,
    progress: Progress = emit,
) -> None:
    require_root()
    source = _validate_source_file(image)
    target = os.path.realpath(device)
    _check_block_device(target)
    target_info = validate_target_device(target, expected_identity)
    if target_info.size < 32 * 1024 * 1024:
        raise ValueError("Drive is too small to write safely.")
    ensure_source_not_on_target(source, target)
    unmount_device(target, progress)
    # Revalidate after unmount in case the device disappeared/reappeared.
    target_info = validate_target_device(target, expected_identity)

    src, known_size, compression = image_stream(source)
    if known_size is not None and known_size > target_info.size:
        src.close()
        raise ValueError("Image is larger than the selected drive.")

    progress("stage", name="writing", message=f"Writing {compression} image")
    hasher = hashlib.sha256()
    written = 0
    start = time.monotonic()

    # Read one chunk successfully before changing the target. This catches an
    # empty/trivially-corrupt compressed stream before any destructive write.
    with src:
        first = src.read(CHUNK_SIZE)
        if not first:
            raise ValueError("The selected image produced no data.")
        if len(first) > target_info.size:
            raise ValueError("Decompressed image is larger than the selected drive.")

        # Re-check identity immediately before claiming the whole block device.
        target_info = validate_target_device(target, expected_identity)
        flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_EXCL", 0)
        try:
            fd = os.open(target, flags)
        except OSError as exc:
            if getattr(exc, "errno", None) == 16:  # EBUSY
                raise RuntimeError(
                    "The target became busy after unmounting. Close file-manager/terminal access to the USB and try again."
                ) from exc
            raise
        try:
            _assert_open_target_matches_path(fd, target, target_info.size)
            # Remove stale backup GPT/signature data at the physical end before
            # writing the new image to offset zero.
            _clear_stale_target_tail(fd, target_info.size)

            pending = first
            while True:
                if written + len(pending) > target_info.size:
                    raise ValueError("Decompressed image is larger than the selected drive.")
                view = memoryview(pending)
                while view:
                    n = os.write(fd, view)
                    if n <= 0:
                        raise OSError("Short write to target device.")
                    view = view[n:]
                written += len(pending)
                hasher.update(pending)
                elapsed = max(time.monotonic() - start, 0.001)
                progress(
                    "progress",
                    stage="writing",
                    bytes=written,
                    total=known_size,
                    speed=int(written / elapsed),
                )
                pending = src.read(CHUNK_SIZE)
                if not pending:
                    break

            progress("stage", name="flushing", message="Flushing data to the USB drive")
            os.fsync(fd)
        finally:
            os.close(fd)

    digest = hasher.hexdigest()
    progress("checksum", algorithm="sha256", value=digest, bytes=written)
    _flush_target(target)

    if verify:
        progress("stage", name="verifying", message="Verifying written data from the USB drive")
        verify_hasher = hashlib.sha256()
        checked = 0
        start = time.monotonic()
        with open(target, "rb", buffering=0) as dst:
            remaining = written
            while remaining:
                chunk = dst.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise OSError("Unexpected end of target while verifying.")
                verify_hasher.update(chunk)
                checked += len(chunk)
                remaining -= len(chunk)
                elapsed = max(time.monotonic() - start, 0.001)
                progress(
                    "progress",
                    stage="verifying",
                    bytes=checked,
                    total=written,
                    speed=int(checked / elapsed),
                )
        if verify_hasher.hexdigest() != digest:
            raise RuntimeError("Verification failed: target data does not match the image.")
        progress("verified", algorithm="sha256", value=digest)

    _reread_partitions(target)
    progress("done", bytes=written, sha256=digest)

def partition_path(device: str, number: int = 1) -> str:
    if device[-1:].isdigit():
        return f"{device}p{number}"
    return f"{device}{number}"


def _wait_for(path: str, timeout: float = 10.0) -> None:
    udevadm = command_path("udevadm")
    if udevadm:
        subprocess.run([udevadm, "settle", "--timeout=8"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if os.path.exists(path):
            return
        time.sleep(0.2)
    raise RuntimeError(f"Partition node did not appear: {path}")


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    encoded = encoded[:max_bytes]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return ""


def sanitize_label(label: str, filesystem: str) -> str:
    fs = filesystem.lower()
    fallback = "BOOTCRAFT"
    value = (label or "").strip() or fallback
    # Avoid path/control characters and filesystem-problematic punctuation.
    value = "".join(ch for ch in value if ch.isprintable() and ch not in "\\/:*?\"<>|")
    value = value.strip(" .") or fallback
    if fs == "fat32":
        # FAT volume labels are most portable when restricted to a conservative
        # DOS-compatible ASCII set. This avoids mkfs failures caused by locale/
        # codepage-dependent Unicode or punctuation.
        safe = "".join(ch for ch in value.upper() if ch.isascii() and (ch.isalnum() or ch in " _-"))
        safe = safe.strip() or fallback
        return safe[:11].rstrip()
    if fs == "exfat":
        return value[:15]
    if fs == "ntfs":
        return value[:32]
    if fs == "ext4":
        return _truncate_utf8(value, 16) or fallback[:16]
    return value[:32]


GPT_BASIC_DATA = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"
GPT_LINUX_FILESYSTEM = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"


def partition_script(scheme: str, filesystem: str, *, bootable: bool = False) -> str:
    scheme = scheme.lower()
    filesystem = filesystem.lower()
    if scheme not in {"gpt", "mbr"}:
        raise ValueError(f"Unsupported partition scheme: {scheme}")
    if filesystem not in {"fat32", "exfat", "ntfs", "ext4"}:
        raise ValueError(f"Unsupported filesystem: {filesystem}")
    if scheme == "mbr":
        type_code = {"fat32": "c", "exfat": "7", "ntfs": "7", "ext4": "83"}[filesystem]
        boot = ",*" if bootable else ""
        return f"label: dos\n,,{type_code}{boot}\n"
    type_guid = GPT_LINUX_FILESYSTEM if filesystem == "ext4" else GPT_BASIC_DATA
    return f"label: gpt\n,,{type_guid}\n"


def _filesystem_formatter(filesystem: str) -> tuple[str, list[str]]:
    fs = filesystem.lower()
    command = {
        "fat32": "mkfs.vfat",
        "exfat": "mkfs.exfat",
        "ntfs": "mkfs.ntfs",
        "ext4": "mkfs.ext4",
    }.get(fs)
    if not command:
        raise ValueError(f"Unsupported filesystem: {filesystem}")
    return require_command(command), []


def windows_payload_bytes(scan: tuple[list[tuple[str, str, int]], tuple[str, str] | None, int]) -> int:
    _files, special_wim, total = scan
    if special_wim:
        total += os.path.getsize(special_wim[0])
    return total


def format_drive(
    device: str,
    scheme: str,
    filesystem: str,
    label: str,
    expected_identity: str | None = None,
    progress: Progress = emit,
) -> None:
    require_root()
    target = os.path.realpath(device)
    _check_block_device(target)
    info = validate_target_device(target, expected_identity)
    if info.size < 32 * 1024 * 1024:
        raise ValueError("Drive is too small to format safely.")

    fs = filesystem.lower()
    script = partition_script(scheme, fs)
    # Resolve every required destructive-stage tool before touching the drive.
    wipefs = require_command("wipefs")
    sfdisk = require_command("sfdisk")
    formatter, _ = _filesystem_formatter(fs)

    unmount_device(target, progress)
    validate_target_device(target, expected_identity)

    progress("stage", name="partitioning", message="Creating partition table")
    _run([wipefs, "--all", "--force", target])
    _run([sfdisk, "--wipe", "always", target], input_text=script)
    _reread_partitions(target)
    part = partition_path(target)
    _wait_for(part)
    # A new partition can expose a stale old filesystem signature and trigger
    # desktop automount before mkfs. Unmount once more immediately beforehand.
    unmount_device(target, progress)
    validate_target_device(target, expected_identity)

    clean_label = sanitize_label(label, fs)
    progress("stage", name="formatting", message=f"Formatting {fs.upper()}")
    if fs == "fat32":
        _run([formatter, "-F", "32", "-n", clean_label, part])
    elif fs == "exfat":
        _run([formatter, "-n", clean_label, part])
    elif fs == "ntfs":
        _run([formatter, "-f", "-L", clean_label, part])
    elif fs == "ext4":
        _run([formatter, "-F", "-L", clean_label, part])

    sync = command_path("sync")
    if sync:
        subprocess.run([sync], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _reread_partitions(target)
    progress("done", partition=part, filesystem=fs, label=clean_label)

def sha256_file(path: str, progress: Progress | None = None) -> str:
    total = os.path.getsize(path)
    done = 0
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress("progress", stage="hashing", bytes=done, total=total, speed=0)
    return h.hexdigest()


def has_uefi_boot_file(root: str) -> bool:
    efi_boot = os.path.join(root, "EFI", "BOOT")
    if not os.path.isdir(efi_boot):
        # Case-insensitive fallback for ISO9660/UDF layouts.
        for walk_root, _dirs, files in os.walk(root):
            rel_root = os.path.relpath(walk_root, root).replace("\\", "/").lower()
            if rel_root == "efi/boot" and any(
                name.lower().startswith("boot") and name.lower().endswith(".efi") for name in files
            ):
                return True
        return False
    return any(name.lower().startswith("boot") and name.lower().endswith(".efi") for name in os.listdir(efi_boot))


def _find_case_insensitive(root: str, relative: str) -> str | None:
    current = root
    for part in relative.replace("\\", "/").split("/"):
        if not os.path.isdir(current):
            return None
        names = {name.lower(): name for name in os.listdir(current)}
        match = names.get(part.lower())
        if match is None:
            return None
        current = os.path.join(current, match)
    return current


def _scan_windows_tree(source_root: str) -> tuple[list[tuple[str, str, int]], tuple[str, str] | None, int]:
    max_fat_file = 4 * 1024 * 1024 * 1024 - 1024 * 1024
    special_wim: tuple[str, str] | None = None
    total = 0
    files: list[tuple[str, str, int]] = []
    for root, _dirs, names in os.walk(source_root):
        for name in names:
            src = os.path.join(root, name)
            if os.path.islink(src):
                continue
            rel = os.path.relpath(src, source_root)
            size = os.path.getsize(src)
            rel_lower = rel.replace("\\", "/").lower()
            if size > max_fat_file:
                if rel_lower == "sources/install.wim":
                    special_wim = (src, os.path.join("sources", "install.swm"))
                    continue
                raise ValueError(f"Windows ISO contains a FAT32-incompatible file larger than 4 GiB: {rel}")
            files.append((src, rel, size))
            total += size
    return files, special_wim, total


def validate_windows_source_tree(source_root: str) -> tuple[list[tuple[str, str, int]], tuple[str, str] | None, int]:
    if not has_uefi_boot_file(source_root):
        raise ValueError("The ISO does not contain standard UEFI removable-media boot files.")
    if _find_case_insensitive(source_root, "sources/boot.wim") is None:
        raise ValueError("The ISO does not contain sources/boot.wim and does not look like Windows installer media.")
    files, special_wim, total = _scan_windows_tree(source_root)
    if special_wim and not command_path("wimlib-imagex"):
        raise RuntimeError("This Windows ISO needs wimlib-imagex to split install.wim. Install the wimtools package.")
    return files, special_wim, total


def _copy_windows_tree(
    source_root: str,
    target_root: str,
    progress: Progress = emit,
    scan: tuple[list[tuple[str, str, int]], tuple[str, str] | None, int] | None = None,
) -> None:
    files, special_wim, total = scan or _scan_windows_tree(source_root)
    copied = 0
    start = time.monotonic()
    progress("stage", name="copying", message="Copying Windows installation files")
    for src, rel, _size in files:
        dst = os.path.join(target_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            while True:
                chunk = fi.read(CHUNK_SIZE)
                if not chunk:
                    break
                fo.write(chunk)
                copied += len(chunk)
                elapsed = max(time.monotonic() - start, 0.001)
                progress("progress", stage="copying", bytes=copied, total=total, speed=int(copied / elapsed))

    if special_wim:
        src, rel_first_part = special_wim
        first_part = os.path.join(target_root, rel_first_part)
        wimlib = require_command("wimlib-imagex")
        os.makedirs(os.path.dirname(first_part), exist_ok=True)
        progress("stage", name="splitting", message="Splitting install.wim for FAT32 compatibility")
        _run([wimlib, "split", src, first_part, "3800", "--check"])


def make_windows_usb(
    image: str,
    device: str,
    label: str = "WINDOWS",
    expected_identity: str | None = None,
    progress: Progress = emit,
) -> None:
    """Create modern Windows 10/11 UEFI install media on FAT32."""
    require_root()
    source = _validate_source_file(image)
    if not source.lower().endswith(".iso"):
        raise ValueError("Windows installer mode requires an ISO image.")
    target = os.path.realpath(device)
    _check_block_device(target)
    target_info = validate_target_device(target, expected_identity)
    ensure_source_not_on_target(source, target)

    # Resolve all always-required tools before any destructive operation.
    wipefs = require_command("wipefs")
    sfdisk = require_command("sfdisk")
    mkfs = require_command("mkfs.vfat")
    mount = require_command("mount")
    umount = require_command("umount")
    sync_cmd = require_command("sync")

    with tempfile.TemporaryDirectory(prefix="bootcrafter-") as temp:
        iso_mnt = os.path.join(temp, "iso")
        usb_mnt = os.path.join(temp, "usb")
        os.makedirs(iso_mnt)
        os.makedirs(usb_mnt)
        iso_mounted = False
        usb_mounted = False
        try:
            # Validate the ISO and capacity BEFORE erasing the USB.
            progress("stage", name="validating", message="Validating Windows installer ISO")
            _run([mount, "-o", "loop,ro,nosuid,nodev,noexec", source, iso_mnt])
            iso_mounted = True
            scan = validate_windows_source_tree(iso_mnt)
            required = windows_payload_bytes(scan) + WINDOWS_FREE_SPACE_MARGIN
            if required > target_info.size:
                raise ValueError(
                    "The selected USB drive is too small for this Windows installer. "
                    f"Need approximately {required / (1024 ** 3):.2f} GiB including filesystem overhead."
                )

            unmount_device(target, progress)
            target_info = validate_target_device(target, expected_identity)
            if required > target_info.size:
                raise ValueError("The selected USB drive capacity changed. Refresh and select the drive again.")

            progress("stage", name="partitioning", message="Preparing FAT32 Windows installer partition")
            _run([wipefs, "--all", "--force", target])
            _run([sfdisk, "--wipe", "always", target], input_text=partition_script("mbr", "fat32", bootable=True))
            _reread_partitions(target)
            part = partition_path(target)
            _wait_for(part)
            # The new partition can briefly expose stale filesystem bytes from
            # the previous layout. Defeat any automount before formatting it.
            unmount_device(target, progress)
            validate_target_device(target, expected_identity)
            _run([mkfs, "-F", "32", "-n", sanitize_label(label or "WINDOWS", "fat32"), part])

            # A desktop automounter may react to the newly created filesystem.
            # Unmount once more before attaching it to BootCrafter's private mount.
            unmount_device(target, progress)
            validate_target_device(target, expected_identity)
            _run([mount, "-o", "rw,nosuid,nodev", part, usb_mnt])
            usb_mounted = True
            _copy_windows_tree(iso_mnt, usb_mnt, progress, scan=scan)
            progress("stage", name="flushing", message="Flushing Windows installer files")
            _run([sync_cmd])
            if not has_uefi_boot_file(usb_mnt):
                raise RuntimeError("UEFI boot file verification failed after copy.")
            if _find_case_insensitive(usb_mnt, "sources/boot.wim") is None:
                raise RuntimeError("Windows boot.wim verification failed after copy.")
        finally:
            if usb_mounted:
                subprocess.run([umount, "--", usb_mnt], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if iso_mounted:
                subprocess.run([umount, "--", iso_mnt], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _reread_partitions(target)
    progress("done", partition=partition_path(target), filesystem="fat32", mode="windows-uefi")

