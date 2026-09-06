# Security Policy

BootCrafter performs privileged, destructive block-device operations, so security reports are treated as high priority.

## Supported version

| Version | Supported |
| --- | --- |
| 1.0.5 | Yes |
| 1.0.4 and older | No |

## Reporting a vulnerability

Please use this repository's **GitHub Security Advisory / private vulnerability reporting** flow when available. Do not publish exploit details, proof-of-concept privilege-escalation code, or destructive-device bypass instructions in a public issue before a fix is available.

Useful reports include the affected version, distribution, reproduction conditions, expected behavior, observed behavior, and whether the issue crosses the unprivileged-GUI / privileged-helper boundary.

## Security boundaries

BootCrafter's intended security model is:

- the desktop GUI runs unprivileged;
- raw disk work is performed only by the installed root-owned helper through PolicyKit;
- the helper uses isolated Python startup and a minimal environment;
- destructive targets are explicitly selected and revalidated before and during operations;
- source checkouts are not trusted for privileged execution.

A regression in any of these boundaries should be treated as security-sensitive.
