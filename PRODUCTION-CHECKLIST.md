# BootCrafter Linux 1.0.5 — Production Acceptance Checklist

Use disposable/test USB media. Every destructive test must confirm the selected target before pressing START.

## Automated release gates

- [x] Python compilation and version check
- [x] 32/32 backend/security tests
- [x] Raw image write + SHA-256 read-back regression
- [x] Compressed-image preflight and late-corruption-before-erase regressions
- [x] Explicit target/no-auto-switch regression
- [x] Operation-local device identity fallback when helper token is omitted
- [x] Raw verification FD identity/capacity binding regression
- [x] System/live/swap protection regressions
- [x] Internal non-removable eMMC discovery exclusion
- [x] Stable source snapshot/readability regression
- [x] Trusted command-path regressions
- [x] Broken progress-pipe resilience regression
- [x] Windows ISO validation/capacity regressions
- [x] Format dependency and MBR capacity regressions
- [x] GUI safety/layout smoke test
- [x] Root GUI refusal
- [x] PolicyKit policy validation
- [x] Isolated Python (`-I -S`) wrapper validation
- [x] Malicious-current-directory import-hijack package regression
- [x] `pkexec` Debian dependency validation; `policykit-1` rejected
- [x] Package ownership/permission/shell-syntax checks
- [x] Installed-layout import/helper/GUI smoke tests

## Physical hardware acceptance — required before broad public release

### Linux / Proxmox raw mode

- [ ] Write a known-good Proxmox/Linux hybrid ISO to a disposable physical USB
- [ ] Keep **Verify after writing** enabled and confirm verification succeeds
- [ ] Replug the USB and confirm the expected partitions appear
- [ ] UEFI-boot a test machine from the USB
- [ ] Reach the expected installer/live boot screen

### Windows UEFI mode

- [ ] Use a genuine known-good Windows 10/11 x64 ISO
- [ ] Create the installer USB on a disposable physical drive
- [ ] Test an ISO with normal `install.esd`/small `install.wim`
- [ ] If advertised, test an ISO with `install.wim` >4 GiB and confirm split-WIM creation
- [ ] UEFI-boot a test machine and reach Windows Setup

### Format / recovery mode

- [ ] GPT + FAT32
- [ ] GPT + ext4
- [ ] GPT + exFAT when `exfatprogs` is installed
- [ ] GPT + NTFS when `ntfs-3g` is installed
- [ ] MBR + FAT32 on a drive <=2 TiB
- [ ] Confirm >2 TiB MBR is rejected before destructive work

### Failure handling

- [ ] Remove/reinsert an idle selected USB and confirm selection is cleared/revalidated
- [ ] Confirm system/root disk never appears as an eligible destructive target
- [ ] Confirm ISO stored on target USB is rejected
- [ ] Close the GUI during a disposable test write and confirm helper behavior is safe/observable
- [ ] Test desktop automount behavior on Ubuntu/Mint/Zorin and Debian target environments

## Release sign-off

Only call the release **hardware-accepted production** after the relevant physical workflow boxes above are checked and recorded with distro, kernel, USB model, image hash, firmware/UEFI mode, and result.
