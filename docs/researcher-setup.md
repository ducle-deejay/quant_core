# Installing nautilus-bridge

Researchers install `nautilus-bridge` from the private package index with `scripts/researcher_setup.sh`. Before sending the script, fill in `INDEX_HOST` with the index host on Tailscale.

The researcher needs Tailscale access to that host and a user name and password for the package index, then runs:

```bash
export INDEX_USER=<user> INDEX_PASSWORD=<password>
sh researcher_setup.sh
```

The script prints `ok` when the installation works, and the environment is at `~/nautilus-env`.

To update, change `VERSION` in the script, send it again, and the researcher runs it again.
