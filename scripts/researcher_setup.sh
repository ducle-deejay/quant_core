#!/bin/sh
# Installs nautilus-bridge and mounts the published catalog for a Linux researcher.
set -eu

SERVER_HOST="${1:?usage: sh researcher_setup.sh <server-host>}"
VERSION="0.5.0"
MOUNT_POINT="/mnt/published"

read_credentials() {
    printf 'Package index user: '; read -r INDEX_USER
    printf 'Package index password: '; stty -echo; read -r INDEX_PASSWORD; stty echo; echo
    printf 'SMB user: '; read -r SMB_USER
    printf 'SMB password: '; stty -echo; read -r SMB_PASSWORD; stty echo; echo
}

install_env() {
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"

    uv venv --clear --python 3.14 --seed ~/nautilus-env
    ~/nautilus-env/bin/pip install \
        --index-url "http://${INDEX_USER}:${INDEX_PASSWORD}@${SERVER_HOST}:8080/simple/" \
        --trusted-host "$SERVER_HOST" \
        "nautilus-bridge==$VERSION"
    ~/nautilus-env/bin/python -c "import nautilus_bridge.backtest.runner; print('ok')"
}

mount_catalog() {
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
}

# python-dotenv's find_dotenv(usecwd=True) walks from the working directory up to /, so ~/.env covers backtests run anywhere under $HOME.
write_env() {
    touch ~/.env
    sed -i '/^DATA_ROOT=/d' ~/.env
    echo "DATA_ROOT=$MOUNT_POINT" >> ~/.env
    echo "DATA_ROOT=$MOUNT_POINT written to ~/.env"
}

read_credentials
install_env
mount_catalog
write_env
