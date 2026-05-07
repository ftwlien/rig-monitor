# Security Policy

## Supported versions

Security fixes are applied to the latest `main` branch.

## Reporting a vulnerability

Please report security issues privately to the repository owner instead of opening a public issue with exploit details.

## Important security notes

- `rig-monitor` is a local terminal dashboard for GPU rigs. It should be run only on machines you control.
- The installer adds a limited sudoers rule for the local `gputemps` helper so VRAM/junction temperature readings can work without typing a password every time.
- Review installer scripts before running them on production machines, especially any command that modifies `/usr/local/bin` or `/etc/sudoers.d`.
- Do not publish screenshots or logs that expose public IPs, hostnames, usernames, rental IDs, API keys, SSH keys, tokens, or other private infrastructure details.
- Do not paste private keys, Vast.ai API keys, Telegram bot tokens, or cloud credentials into issues.
- If you fork or modify this project, avoid committing machine-specific config, credentials, SSH material, logs, or generated local state.
