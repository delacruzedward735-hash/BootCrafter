from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Iterable

# Mounts used by the running OS must never be treated as disposable media.
# Common removable-media mount locations are allowed and can be unmounted by
# the privileged helper before writing.
PROTECTED_MOUNTS = {
    "/",
    "/boot",
    "/boot/efi",
    "/cdrom",
    "/run/live/medium",
    "/run/archiso/bootmnt",
}
SAFE_REMOVABLE_MOUNT_PREFIXES = (
    "/media/",
    "/run/media/",
    "/mnt/",
)


@dataclass(frozen=True)
class Device:
    path: str
    size: int
    model: str
    vendor: str
    transport: str
    removable: bool
    hotplug: bool
    read_only: bool
    protected: bool
    serial: str = ""
    wwn: str = ""
    maj_min: str = ""

    @property
    def display(self) -> str:
        gib = self.size / (1024 ** 3) if self.size else 0
        identity = " ".join(x for x in (self.vendor, self.model) if x).strip() or "USB drive"
        transport = self.transport.upper() if self.transport else "REMOVABLE"
        return f"{identity} — {gib:.1f} GiB — {self.path} [{transport}]"

    @property
    def strong_hardware_id(self) -> bool:
        return bool(self.serial.strip() or self.wwn.strip())

    @property
    def identity_token(self) -> str:
        """Path-bound token used to detect target changes before erasing.

        Serial/WWN are included when the device exposes them. The path is also
        included so two otherwise-identical flash drives cannot silently swap
        selection in the GUI. A serial-less replacement at the exact same
        kernel path cannot be perfectly distinguished on Linux, so the GUI
        surfaces that as a weaker identity case and still requires destructive
        confirmation.
        """
        payload = {
            "path": os.path.realpath(self.path),
            "size": int(self.size),
            "model": self.model.strip(),
            "vendor": self.vendor.strip(),
            "transport": self.transport.strip().lower(),
            "serial": self.serial.strip(),
            "wwn": self.wwn.strip(),
            "maj_min": self.maj_min.strip(),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes"}


def _mountpoints(node: dict[str, Any]) -> list[str]:
    raw = node.get("mountpoints")
    if isinstance(raw, list):
        values = [str(x) for x in raw if x]
    elif raw:
        values = [str(raw)]
    else:
        values = []
    single = node.get("mountpoint")
    if single and str(single) not in values:
        values.append(str(single))
    return values


def _is_protected_mount(mount: str) -> bool:
    normalized = mount.rstrip("/") or "/"
    if normalized.upper() == "[SWAP]":
        return True
    if normalized in PROTECTED_MOUNTS:
        return True
    if normalized.startswith("/run/live/medium/") or normalized.startswith("/run/archiso/bootmnt/"):
        return True
    if normalized in {"/media", "/run/media", "/mnt"}:
        return False
    if any(normalized.startswith(prefix) for prefix in SAFE_REMOVABLE_MOUNT_PREFIXES):
        return False
    # A block device mounted anywhere else (for example /home, /var, /srv,
    # /data) may be part of the running system or an intentionally mounted
    # data volume. Safety-first behavior is to hide it from destructive targets.
    return normalized.startswith("/")


def _has_protected_mount(node: dict[str, Any]) -> bool:
    if any(_is_protected_mount(m) for m in _mountpoints(node)):
        return True
    return any(_has_protected_mount(child) for child in node.get("children") or [])


def parse_lsblk(payload: str, include_internal: bool = False) -> list[Device]:
    data = json.loads(payload)
    devices: list[Device] = []
    for node in data.get("blockdevices") or []:
        if node.get("type") != "disk":
            continue
        path = str(node.get("path") or node.get("name") or "")
        if not path.startswith("/dev/"):
            continue
        transport = str(node.get("tran") or "").lower()
        removable = _bool(node.get("rm"))
        hotplug = _bool(node.get("hotplug"))
        read_only = _bool(node.get("ro"))
        protected = _has_protected_mount(node)
        external_candidate = removable or hotplug or transport in {"usb", "mmc", "sdio"}
        if (not include_internal and not external_candidate) or protected or read_only:
            continue
        devices.append(
            Device(
                path=path,
                size=int(node.get("size") or 0),
                model=str(node.get("model") or "").strip(),
                vendor=str(node.get("vendor") or "").strip(),
                transport=transport,
                removable=removable,
                hotplug=hotplug,
                read_only=read_only,
                protected=protected,
                serial=str(node.get("serial") or "").strip(),
                wwn=str(node.get("wwn") or "").strip(),
                maj_min=str(node.get("maj:min") or node.get("maj_min") or "").strip(),
            )
        )
    return sorted(devices, key=lambda d: d.path)


def lsblk_json() -> str:
    fields = "NAME,PATH,TYPE,SIZE,MODEL,VENDOR,TRAN,RM,HOTPLUG,MOUNTPOINTS,FSTYPE,LABEL,RO,SERIAL,WWN,MAJ:MIN"
    result = subprocess.run(
        ["lsblk", "--json", "--bytes", "--paths", "--output", fields],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def list_devices(include_internal: bool = False) -> list[Device]:
    return parse_lsblk(lsblk_json(), include_internal=include_internal)


def find_node(tree: Iterable[dict[str, Any]], path: str) -> dict[str, Any] | None:
    for node in tree:
        if str(node.get("path") or node.get("name") or "") == path:
            return node
        found = find_node(node.get("children") or [], path)
        if found:
            return found
    return None


def validate_target_device(path: str, expected_identity: str | None = None) -> Device:
    real = os.path.realpath(path)
    candidates = parse_lsblk(lsblk_json(), include_internal=False)
    for device in candidates:
        if os.path.realpath(device.path) != real:
            continue
        if device.protected:
            raise ValueError("Refusing to operate on a disk used by the running system.")
        if device.read_only:
            raise ValueError("The selected drive is read-only.")
        if device.size <= 0:
            raise ValueError("The selected drive reports an invalid size.")
        if expected_identity and device.identity_token != expected_identity:
            raise ValueError(
                "The device at this /dev path changed after selection. Refresh the drive list and select the USB again."
            )
        return device
    raise ValueError("Target is not a writable removable/external whole block device.")
