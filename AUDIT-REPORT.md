# BootCrafter Linux 1.0.2 — Functional/Safety Audit

## Result

**Automated/source/package audit: PASS**

This release replaces 1.0.1 after the audit found hardware-facing safety and compatibility gaps that were not covered by the earlier test suite.

## Important fixes made during the audit

1. Destructive target selection is now explicit. No USB is selected automatically, and a removed selected USB is never replaced silently by another drive.
2. System-disk protection now blocks non-removable-style mounted system/data paths such as `/home`, `/var`, `/srv`, `/data`, live media, swap, `/`, `/boot`, and `/boot/efi`; normal removable mounts under `/media`, `/run/media`, and `/mnt` may be unmounted for use.
3. Device identity now incorporates path, capacity, vendor/model, serial, WWN, transport, and major:minor information where available. Serial/WWN-less media produces an extra confirmation warning.
4. Raw writes read the first source chunk before changing the target, revalidate immediately before opening, claim the block device with `O_EXCL`, verify the opened device/path and capacity, clear stale end-of-disk metadata, `fsync`, flush block buffers, and optionally perform full SHA-256 read-back verification.
5. Windows mode validates the ISO and required capacity before erasing the target.
6. Windows and format modes resolve required destructive-stage utilities before erasing the target.
7. FAT32/NTFS/exFAT/ext4 partition creation now uses compatible MBR/GPT partition type identifiers.
8. Windows and format flows re-unmount newly created partitions before formatting/copying to reduce desktop automounter races caused by stale filesystem bytes.
9. FAT32 labels now use a conservative portable ASCII subset; ext4 labels are limited by UTF-8 byte length.
10. Desktop-session command discovery checks `/usr/sbin`, `/usr/bin`, `/sbin`, and `/bin`, avoiding false missing-tool reports from a restricted GUI `PATH`.
11. All operation-changing GUI controls are frozen while a privileged operation is active.
12. Debian package permissions were cleaned; no setuid/setgid or world-writable shipped paths were found.
13. `wimtools` is Recommended rather than mandatory because Linux raw writing does not require it; oversized Windows `install.wim` media still checks for it before erasure.

## Verification performed

- Python compile check: PASS
- Backend unit tests: **23/23 PASS**
- Raw image write + SHA-256 read-back pipeline against an emulated target file: PASS
- Corrupt compressed-image pre-write protection test: PASS
- System/live/swap/data-mount protection tests: PASS
- Device identity/path-change tests: PASS
- Windows ISO tree validation tests: PASS
- Windows insufficient-capacity-before-erasure test: PASS
- Oversized Windows WIM dependency test: PASS
- Windows file-copy tree test: PASS
- Format formatter-before-erasure test: PASS
- GPT/MBR partition-type generation tests: PASS
- Label sanitation tests: PASS
- ZIP/compressed-stream tests: PASS
- Helper command-line parsing: PASS
- Responsive GUI at 720x520 under Xvfb: PASS
- No-auto-target/no-auto-switch GUI safety test: PASS
- Busy-state control-lock test: PASS
- Installed-package import/compile/helper tests: PASS
- Installed-package window startup under Xvfb: PASS
- Desktop `StartupWMClass` vs actual `WM_CLASS`: PASS
- Launcher/icon paths: PASS
- Debian package metadata: PASS
- Package permission audit: PASS
- Old upstream branding scan: PASS
- `shell=True` / `os.system` / dynamic `eval`/`exec` source scan: PASS

## Environment limitation

The build environment does **not** expose a writable physical USB block device and does not contain every optional runtime formatter (`sfdisk`, `mkfs.vfat`, etc.). Those tools are declared as Debian dependencies/recommendations and their command construction/pre-erasure behavior is unit-tested, but a real USB write-and-boot test on the target Linux machine remains the final hardware acceptance test.

For the Proxmox ISO workflow, use **Linux/Proxmox ISO or disk image (raw)** with **Verify after writing** enabled.
