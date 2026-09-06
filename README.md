# BootCrafter Linux 1.0.5

BootCrafter Linux is a Linux-native bootable USB creator focused on safe, verifiable disk writing. Version 1.0.5 is the production-hardening release of the 1.0.x line.

BootCrafter is an independent project and is not affiliated with, endorsed by, or sponsored by Rufus or its maintainers.

## Supported workflows

- **Linux / Proxmox / hybrid ISO and raw images** — byte-for-byte whole-device writing.
- **Compressed disk images** — `.gz`, `.xz`, `.bz2`, single-image `.zip`, and optional `.zst/.zstd`.
- **Windows 10/11 UEFI installer media** — FAT32 installer USB with automatic `install.wim` splitting when `wimlib-imagex` is available.
- **USB recovery / format mode** — GPT or MBR with FAT32, exFAT, NTFS, or ext4.
- **SHA-256 verification** — optional full post-write read-back verification for raw-image mode plus standalone image checksum calculation.

## Production safety design

BootCrafter deliberately separates the desktop GUI from privileged disk operations.

- The GUI is expected to run as a normal desktop user and refuses normal root-GUI startup.
- Destructive operations are delegated to the installed root-owned helper through PolicyKit/`pkexec`.
- The Debian package installs an explicit PolicyKit action for `/usr/lib/bootcrafter-linux/bootcrafter-helper`.
- The privileged helper starts with a minimal environment and Python isolated mode (`-I -S`), so the current directory, user site-packages, `PATH`, `PYTHONPATH`, and `PYTHONHOME` cannot redirect privileged imports or command execution.
- Privileged command discovery uses only trusted system directories (`/usr/sbin`, `/usr/bin`, `/sbin`, `/bin`).
- Source-checkout mode cannot elevate user-writable Python code; install the `.deb` before performing destructive operations.
- The selected source image is opened as a stable inode snapshot after authorization. The helper does not use administrator privileges to read files that the invoking desktop user could not normally read.
- The helper keeps working if the GUI or its progress pipe disappears during a write; a desktop crash does not intentionally abort the root writer midway.

## Device protection

- BootCrafter never automatically chooses a destructive target.
- A selected drive that disappears is cleared rather than silently replaced.
- System/live/swap/read-only disks are filtered out; internal non-removable/non-hotplug eMMC devices are not offered merely because their transport is `mmc`.
- Mounted system/data locations such as `/`, `/boot`, `/boot/efi`, `/home`, `/var`, `/srv`, and similar non-removable mount paths are protected.
- Normal removable mounts under `/media`, `/run/media`, and `/mnt` can be unmounted for use.
- Device identity is locked at operation start and rechecked using path, size, vendor/model, transport, serial, WWN, and major:minor data where available, even when the helper is invoked directly without a GUI-supplied identity token.
- Serial/WWN-less USB drives trigger an additional caution because no software can perfectly distinguish two truly identical serial-less devices that replace one another at the same kernel path.
- The helper refuses to erase a target that stores the selected source image.

## Raw image reliability

- Checks target capacity before writing.
- Fully decodes compressed images **before unmounting or erasing the target**, catching late CRC/decompression failures before destructive work begins.
- Reads raw images successfully before target modification.
- Claims the raw block target with an exclusive open after unmounting.
- Revalidates the device immediately before opening and checks the opened device identity/capacity.
- Clears stale backup-GPT/end-of-disk signatures before the new image is written.
- Handles short writes explicitly.
- Calls `fsync` and flushes block buffers when supported.
- Optional SHA-256 read-back verification revalidates the selected device, binds the verification file descriptor to the same block-device identity/capacity, reads exactly the bytes that were written, and compares them with the write-time digest.

## Windows installer mode

Windows mode is intentionally **UEFI-focused**.

Before erasing the USB, BootCrafter:

1. Opens the selected ISO as a stable source snapshot.
2. Attaches that exact inode to a read-only loop device.
3. Mounts the ISO read-only with `nosuid,nodev,noexec`.
4. Verifies standard UEFI removable-media boot files and `sources/boot.wim`.
5. Checks required target capacity with filesystem overhead margin.
6. Checks for `wimlib-imagex` before erasure when an oversized `install.wim` must be split.

The target is then prepared as an active MBR FAT32 installer USB. Essential boot files are checked after copying. Temporary mount cleanup is strictly non-recursive so a failed emergency unmount cannot cause cleanup code to walk into the mounted USB filesystem.

Windows To Go, UEFI:NTFS, TPM/Secure Boot bypass customization, and legacy-BIOS repair modes are not implemented.

## Format mode

Format/recovery mode supports:

- Partition scheme: GPT or MBR
- Filesystems: FAT32, exFAT, NTFS, ext4
- Sanitized volume labels appropriate to each filesystem

Required formatter commands are resolved before destructive partition changes. MBR is conservatively limited to targets up to 2 TiB; use GPT for larger devices.

## Install on Debian / Ubuntu / Linux Mint / Zorin

Install the provided package:

```bash
cd ~/Downloads
sudo apt install ./bootcrafter-linux_1.0.5_all.deb
```

Then launch **BootCrafter Linux** from the application menu or run:

```bash
bootcrafter-linux
```

Do **not** run the GUI with `sudo`. BootCrafter requests administrator authorization only when the disk helper needs it.

### Package dependencies

Required by the Debian package:

```text
python3 >= 3.10
python3-tk
util-linux
fdisk
pkexec
dosfstools
e2fsprogs
mount
coreutils
```

Recommended optional packages:

```text
wimtools     oversized Windows install.wim splitting
exfatprogs   exFAT format mode
ntfs-3g      NTFS format mode
zstd         .zst/.zstd raw images
```

## Source development

```bash
./scripts/verify.sh
./scripts/run-dev.sh
```

For security, a source checkout may run the UI and checksum features but does not elevate its user-writable Python helper. Build and install the package before testing destructive USB operations:

```bash
./INSTALL.sh
sudo apt install ./dist/bootcrafter-linux_1.0.5_all.deb
```

## Verification and production audit

Run:

```bash
./scripts/verify.sh
```

The 1.0.5 release audit covers Python compilation, **32 backend/security tests**, helper CLI parsing, GUI layout and destructive-target safety under Xvfb, trusted command resolution, root-GUI refusal, broken-progress-pipe resilience, PolicyKit policy validation, isolated-Python import-hijack regression tests, package ownership/permission checks, launcher/icon validation, and installed-package smoke testing. `scripts/audit-package.sh` independently audits the built `.deb`.

See `AUDIT-REPORT.md` for the release-specific audit record.

## Hardware acceptance note

Disk-writing tools are inherently destructive. The software and package can be audited extensively without real hardware, but automated file-backed tests cannot prove that every USB controller, firmware, UEFI implementation, or physical machine will boot correctly. Before broad public distribution, perform at least one real **ISO → USB → read-back verification → boot** acceptance test on each workflow you intend to advertise (for example Proxmox/Linux raw mode and Windows UEFI mode).

## Project links

- Website: https://bootcrafter-linux.vercel.app
- Source: https://github.com/delacruzedward735-hash/BootCrafter
- Releases: https://github.com/delacruzedward735-hash/BootCrafter/releases

The product website is intentionally maintained separately from this application-source repository.

## License

BootCrafter-authored code is licensed under the **MIT License**. See `LICENSE`. External programs invoked by BootCrafter remain under their respective licenses; see `NOTICE.md`.
