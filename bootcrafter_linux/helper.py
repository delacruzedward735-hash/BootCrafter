from __future__ import annotations

import argparse

from .operations import emit, format_drive, make_windows_usb, write_image


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bootcrafter-helper")
    sub = p.add_subparsers(dest="command", required=True)

    w = sub.add_parser("write")
    w.add_argument("--image", required=True)
    w.add_argument("--device", required=True)
    w.add_argument("--identity", default="")
    w.add_argument("--verify", choices=("yes", "no"), default="yes")

    win = sub.add_parser("windows")
    win.add_argument("--image", required=True)
    win.add_argument("--device", required=True)
    win.add_argument("--identity", default="")
    win.add_argument("--label", default="WINDOWS")

    f = sub.add_parser("format")
    f.add_argument("--device", required=True)
    f.add_argument("--identity", default="")
    f.add_argument("--scheme", choices=("gpt", "mbr"), default="gpt")
    f.add_argument("--filesystem", choices=("fat32", "exfat", "ntfs", "ext4"), default="fat32")
    f.add_argument("--label", default="BOOTCRAFT")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    expected = args.identity or None
    try:
        if args.command == "write":
            write_image(args.image, args.device, verify=args.verify == "yes", expected_identity=expected)
        elif args.command == "windows":
            make_windows_usb(args.image, args.device, args.label, expected_identity=expected)
        elif args.command == "format":
            format_drive(
                args.device,
                args.scheme,
                args.filesystem,
                args.label,
                expected_identity=expected,
            )
        return 0
    except Exception as exc:
        emit("error", message=str(exc), kind=type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
