# Contributing to BootCrafter Linux

Thank you for helping improve BootCrafter.

## Development setup

BootCrafter uses Python 3.10+ and Tk. On Debian/Ubuntu-family systems, install the development/runtime tools you need, then run:

```bash
./scripts/verify.sh
./scripts/run-dev.sh
```

The source checkout is intentionally not used as a privileged disk helper. For destructive-device testing, build and install the Debian package first:

```bash
./INSTALL.sh
sudo apt install ./dist/bootcrafter-linux_1.0.5_all.deb
```

## Before opening a pull request

Run all release checks:

```bash
./scripts/verify.sh
./scripts/build-deb.sh
./scripts/audit-package.sh
```

Keep destructive operations behind the installed PolicyKit helper, use trusted absolute/system command resolution, avoid shell command construction, and preserve explicit device selection/revalidation.

## Hardware testing

Only test writes and format operations on disposable removable media. Never use a system disk, a drive containing needed data, or a shared production device for development testing.

## Pull requests

Keep changes focused, explain user-visible behavior and safety impact, add regression tests for backend changes, and update `CHANGELOG.md` when behavior changes.
