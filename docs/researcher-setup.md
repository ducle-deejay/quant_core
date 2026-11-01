# Researcher setup

Researchers on Linux install `nautilus-bridge` and mount the published catalog with `scripts/researcher_setup.sh`. Before sending the script, fill in `SERVER_HOST` with the server host on Tailscale; it serves both the package index and the `published` SMB share.

The researcher needs Tailscale access to that host, a user name and password for the package index, and a user name and password for the SMB share, then runs:

```bash
export INDEX_USER=<index-user> INDEX_PASSWORD=<index-password>
export SMB_USER=<smb-user> SMB_PASSWORD=<smb-password>
sh researcher_setup.sh
```

The script asks for the researcher's `sudo` password to install `cifs-utils` and add the mount. It prints `ok` when the package works and `mount ok` when the catalog is readable. The environment is at `~/nautilus-env` and the catalog is mounted read-only at `/mnt/published`, again after every reboot.

Backtests find the catalog through a `.env` file next to the backtest script containing `DATA_ROOT=/mnt/published`.

To update, change `VERSION` in the script, send it again, and the researcher runs it again.
