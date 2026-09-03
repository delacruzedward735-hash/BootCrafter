# BootCrafter Linux 1.0.3 UI regression audit

BootCrafter Linux 1.0.3 changes the application interface while retaining the audited 1.0.2 disk-operation backend.

Verified in this build:

- 23/23 backend unit tests pass.
- Helper CLI entry points compile and load.
- The GUI opens at 760x560 under Xvfb with START and CLOSE fully visible.
- Device discovery does not auto-select a destructive target.
- A disappeared selected USB is cleared rather than replaced by another drive.
- Raw mode disables partition, target-system, filesystem, label and unsupported format controls.
- Windows mode fixes MBR/UEFI/FAT32 and enables only the real volume-label setting.
- Format-only mode enables the real GPT/MBR, filesystem and volume-label settings.
- Busy state disables every operation-changing control and the close action.
- Advanced safety information and the log toggle independently without changing operation state.
- Launcher icons remain valid in all packaged sizes.

The 1.0.2 physical-device caveat still applies: automated tests and file-backed write/verify tests cannot replace a final write-and-boot test on real USB hardware.
