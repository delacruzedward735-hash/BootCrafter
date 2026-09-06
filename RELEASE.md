# BootCrafter Linux Release Process

BootCrafter 1.0.5 is the current production-audited software baseline.

## Release gate

Before tagging a release:

1. Run `./scripts/verify.sh`.
2. Run `./scripts/build-deb.sh`.
3. Run `./scripts/audit-package.sh`.
4. Record at least one physical disposable-USB acceptance test for every workflow advertised for that release.
5. Confirm `CHANGELOG.md`, `README.md`, `SECURITY.md`, `NOTICE.md`, and the version in `bootcrafter_linux/__init__.py` agree.
6. Confirm the repository contains application source only; website deployment files belong in the separate website repository.

## Tagging

Use an annotated or signed tag matching the application version, for example:

```bash
git tag -s v1.0.5 -m "BootCrafter Linux 1.0.5"
git push origin v1.0.5
```

The `Release` GitHub Actions workflow verifies the source, builds and audits the `.deb`, generates `SHA256SUMS.txt`, and publishes both assets to the GitHub Release for tag builds.

## Hardware certification wording

Passing CI and package audit means the source/package passed the automated software release gate. Do not describe a release as universally hardware-certified unless its advertised workflows have been tested on representative physical USB devices and boot targets.
