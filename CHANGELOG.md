# Changelog

## 1.0.3 — compact Windows-style workflow UI

- Rebuilt the main Tkinter interface into a compact light utility layout with Drive Properties, Format Options, and Status sections.
- Added a permanently visible START/CLOSE footer so the destructive action cannot be pushed below the window.
- Preserved the audited 1.0.2 disk-writing, device-safety, verification, Windows installer, and formatting backends without weakening their checks.
- Raw mode now keeps partition/target/filesystem/label context visible but disabled, accurately showing that those values come from the selected image.
- Windows mode shows fixed MBR + UEFI + FAT32 settings and keeps only the real volume-label control editable.
- Format-only mode enables the backend-supported GPT/MBR, filesystem, and volume-label controls.
- Cluster-size, extended-label/icon-file, and bad-block controls are intentionally visible but disabled because the current backend does not implement those features; the UI does not pretend they work.
- Added a compact validation check beside the selected image, collapsible advanced safety information, and a collapsible activity log.
- Updated the GUI smoke test for the new layout, including small-window START/CLOSE visibility, mode behavior, no-auto-target safety, and busy-state locking.

## 1.0.2 — safety and functional audit

- Added explicit target selection: BootCrafter no longer auto-selects the first drive and never silently switches to another drive when the selected USB disappears.
- Strengthened system-disk protection for separately mounted system/data paths such as `/home`, `/var`, `/srv`, and other non-removable mount locations.
- Extended device identity with path, WWN and major:minor data; added a warning for serial/WWN-less devices.
- Raw writer now reads the first source chunk before destructive changes, uses an exclusive block-device open, checks the opened target against the current path, and clears stale backup-GPT/end-of-disk metadata before writing.
- Windows mode now verifies required target capacity before unmounting/erasing the USB.
- Windows mode resolves all always-required commands before destructive work and re-unmounts after `mkfs.vfat` to reduce desktop automounter races.
- Format mode now resolves the selected filesystem formatter before erasing the target.
- Added filesystem-appropriate MBR/GPT partition type identifiers instead of generic partition types.
- System command lookup now checks standard sbin/bin paths so desktop sessions with a minimal `PATH` do not report false missing-command errors.
- Zstandard decompressor stderr no longer uses a pipe that could theoretically deadlock on excessive error output.
- All operation-changing GUI controls are locked while a privileged operation is running.
- Set a stable `WM_CLASS` matching the desktop launcher.
- Moved `wimtools` from hard dependency to Recommended because Linux raw writes do not require it and only oversized Windows WIM media needs it.
- Removed Pillow as a build/verification dependency; PNG dimensions are checked using the Python standard library.
- Expanded automated tests from 16 to 23 backend tests plus stricter GUI safety smoke coverage.
- Hardened FAT32 label sanitization and byte-limited ext4 labels to avoid formatter failures.
- Cleaned Debian package directory permissions so setgid bits are not unintentionally shipped.

## 1.0.1

- Fixed the Create Bootable USB action being pushed below the visible window on common 1366x768/high-DPI desktops.
- Added a fixed action footer; the main body is now vertically scrollable when space is limited.
- Removed misleading editable partition/filesystem/volume-label controls from raw ISO/image mode.
- Added explicit raw-mode guidance: Linux/Proxmox images define their own disk layout and label.
- Windows UEFI mode now clearly shows fixed MBR + FAT32 while keeping Volume label editable.
- Format-only mode keeps GPT/MBR, filesystem and Volume label fully editable and applied.
- Renamed the raw mode label to make Linux/Proxmox usage clearer.
- Reduced log height and overall minimum geometry for better laptop compatibility.

## 1.0.0 — functionality hardening

- Renamed the application and package to BootCrafter Linux.
- Integrated the custom BootCrafter launcher/window icon in multiple desktop sizes.
- Added device identity revalidation to reduce accidental writes after `/dev` path reuse.
- Added protection for common live-media mounts and active swap.
- Added safer dependency preflight checks.
- Added single-image ZIP support and optional Zstandard image support.
- Strengthened raw-write flushing and post-write SHA-256 verification.
- Windows installer ISO is now validated before the target USB is erased.
- Added Windows boot-file verification and preflight handling for oversized `install.wim`.
- Improved partition-table reread and udev settling.
- Improved format/recovery mode and volume-label sanitization.
- Prevents closing the GUI while a destructive helper process is running.
- Expanded automated tests and package verification.
