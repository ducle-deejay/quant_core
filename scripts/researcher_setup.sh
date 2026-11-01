#!/bin/sh
# Installs nautilus-bridge and mounts the published catalog for a Linux researcher;
# needs INDEX_USER, INDEX_PASSWORD, SMB_USER and SMB_PASSWORD in the environment.
set -eu

SERVER_HOST="<server-host>"
VERSION="0.2.0"
MOUNT_POINT="/mnt/published"

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv venv --clear --python 3.14 --seed ~/nautilus-env
~/nautilus-env/bin/pip install \
    --index-url "http://${INDEX_USER}:${INDEX_PASSWORD}@${SERVER_HOST}:8080/simple/" \
    --trusted-host "$SERVER_HOST" \
    "nautilus-bridge==$VERSION"
~/nautilus-env/bin/python -c "import nautilus_bridge.backtest.runner; print('ok')"

if command -v apt-get >/dev/null; then
    sudo apt-get install -y cifs-utils
else
    sudo dnf install -y cifs-utils
fi

printf 'username=%s\npassword=%s\n' "$SMB_USER" "$SMB_PASSWORD" \
    | sudo tee /etc/nautilus-smb-credentials >/dev/null
sudo chmod 600 /etc/nautilus-smb-credentials

sudo mkdir -p "$MOUNT_POINT"
# Drops this mount's previous entry so a rerun leaves exactly one line.
sudo sed -i "\|[[:space:]]$MOUNT_POINT[[:space:]]|d" /etc/fstab
echo "//$SERVER_HOST/published $MOUNT_POINT cifs ro,vers=3.02,credentials=/etc/nautilus-smb-credentials,uid=$(id -u),gid=$(id -g),_netdev,x-systemd.automount 0 0" \
    | sudo tee -a /etc/fstab >/dev/null
sudo systemctl daemon-reload
sudo systemctl start "$(systemd-escape --path --suffix=automount "$MOUNT_POINT")"
ls "$MOUNT_POINT/catalog" >/dev/null && echo "mount ok"

echo "Put this line in the .env next to your backtest script: DATA_ROOT=$MOUNT_POINT"
