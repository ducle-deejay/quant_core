# Researcher setup

Researchers on Linux install `nautilus-bridge` and mount the published catalog with `scripts/researcher_setup.sh`, given the server host on Tailscale, which serves both the package index and the `published` SMB share:

```bash
sh researcher_setup.sh <server-host>
```

The researcher needs Tailscale access to that host, a user name and password for the package index, and a user name and password for the SMB share. The script prompts for them and does not echo the passwords.

The script asks for the researcher's `sudo` password to install `cifs-utils` and add the mount. It prints `ok` when the package works and `mount ok` when the catalog is readable. The environment is at `~/nautilus-env` and the catalog is mounted read-only at `/mnt/published`, again after every reboot.

The script writes `DATA_ROOT=/mnt/published` to `~/.env`, replacing any earlier `DATA_ROOT` line there. Backtests find the catalog by searching for a `.env` from the working directory upward, so any backtest run under the home directory uses it, unless a closer `.env` exists.

To update, change `VERSION` in the script, send it again, and the researcher runs it again.
