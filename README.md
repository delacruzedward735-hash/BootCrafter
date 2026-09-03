# BootCrafter Linux 1.0.3

BootCrafter Linux is a Linux-native bootable USB creator focused on safe, reliable disk writing rather than cosmetic complexity.

## Functional features

- Detects removable/external USB and MMC drives with `lsblk`.
- Never auto-selects a destructive target. If a selected USB disappears, BootCrafter clears the selection instead of silently switching to another drive.
- Blocks disks participating in the running system, including common system/data mount points, live-media mounts, active swap, and read-only disks. Normal removable mounts under `/media`, `/run/media`, and `/mnt` can be safely unmounted for writing.
- Captures a path-bound device identity token using model/vendor/size plus serial, WWN and kernel major:minor data when available, then rechecks it inside the privileged helper before erasing.
- Warns when a USB does not expose a serial/WWN so the model, size and `/dev` path can be checked carefully.
- Writes `.iso`, `.img`, `.raw`, `.bin`, `.gz`, `.xz`, `.bz2`, single-image `.zip`, and optional `.zst/.zstd` images.
- Refuses raw images that exceed the target; compressed images are bounded while decompressing.
- Reads the first image chunk successfully before changing the target.
- Opens raw block targets exclusively after unmounting to reduce remount/in-use races.
- Clears stale end-of-disk metadata before raw writing so an old backup GPT header does not confuse the newly written image.
- Refuses to erase a USB drive that contains the selected source image.
- Optional full byte-for-byte post-write verification using SHA-256 after `fsync` and block-buffer flushing.
- Calculates standalone SHA-256 checksums.
- Windows 10/11 UEFI installer mode:
  - validates UEFI boot files and `sources/boot.wim` **before erasing the USB**;
  - checks that the target has enough capacity **before erasing it**;
  - creates an active MBR FAT32 installer partition with a compatible partition type;
  - splits oversized `sources/install.wim` with `wimlib-imagex` when needed;
  - checks essential boot files after copying;
  - re-unmounts after filesystem creation to avoid desktop automounter races.
- Format/recovery mode with GPT/MBR and FAT32, exFAT, NTFS, or ext4.
- Format mode resolves the required filesystem formatter before any destructive change.
- Uses compatible MBR/GPT partition type identifiers for the selected filesystem.
- Automatic target unmounting and partition-table reread/udev settling.
- GUI runs unprivileged; destructive work is delegated through `pkexec` to a small helper.
- All operation-changing controls are locked while a privileged disk operation is running.
- Custom BootCrafter launcher/window icon included in the Debian package.
- Compact light desktop UI inspired by familiar Windows USB-writer workflows, with Drive Properties, Format Options, Status, and a permanently visible START/CLOSE footer.
- Mode-aware controls: raw images expose their image-defined layout as read-only, Windows mode exposes only settings the backend actually applies, and format-only mode enables the real partition/filesystem/label controls.
- Advanced safety information and the activity log stay collapsed until requested, keeping the main workflow compact.
- Responsive GUI with a fixed bottom action bar, so START/CLOSE stay visible on smaller/high-DPI desktops.

## Install on Debian / Ubuntu / Mint / Zorin

Build and install:

```bash
./INSTALL.sh
sudo apt install ./dist/bootcrafter-linux_1.0.3_all.deb
```

Or install dependencies for source development:

```bash
sudo apt install python3 python3-tk policykit-1 util-linux fdisk dosfstools e2fsprogs mount coreutils
sudo apt install wimtools exfatprogs ntfs-3g zstd   # recommended/optional features
./scripts/run-dev.sh
```

`wimtools` is only required when a Windows ISO contains an `install.wim` that is too large for FAT32. `exfatprogs`, `ntfs-3g`, and `zstd` are only required for their matching optional modes.

## Modes

### Raw image mode

Use this for hybrid Linux ISOs, Proxmox installers, disk images, and similar media. The image is copied byte-for-byte to the whole selected device. Partition scheme, target system, filesystem, and volume-label fields remain visible for context but are read-only/disabled because the source image already contains its own layout.

### Windows installer ISO (UEFI)

Use this for modern Windows 10/11 installer ISOs. BootCrafter validates the ISO and target capacity first, formats the target as FAT32, copies the installer files, and splits an oversized `install.wim` when required. This is UEFI-focused; Windows To Go and special legacy-BIOS repair modes are not implemented.

### Format only

Use this to restore/repartition a USB drive after using it as boot media.

## Verification

Run:

```bash
./scripts/verify.sh
```

The verification suite performs Python compilation, backend unit tests, helper CLI checks, runtime import/version checks, GUI layout and destructive-target-selection smoke tests under Xvfb when available, and dependency-free PNG asset validation.

The release package is additionally extracted and tested using its installed paths before publishing.

## Safety note

Disk-writing tools are inherently destructive. BootCrafter includes multiple independent checks, but always confirm the shown device model, size, and `/dev` path before approving the operation. USB devices that do not expose serial/WWN identifiers receive an extra warning because software cannot perfectly distinguish two truly identical serial-less devices that replace each other at the same kernel path.

Automated tests can validate the write/verify pipeline against files and the GUI/package structure, but this build environment does not expose a writable physical USB block device. A real USB write-and-boot test remains the final hardware acceptance test.

## License

GNU GPL version 3. See `LICENSE`.
