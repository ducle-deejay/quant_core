#!/bin/sh
# Installs nautilus-bridge for a researcher; needs INDEX_USER and INDEX_PASSWORD in the environment.
set -eu

INDEX_HOST="<index-host>"
VERSION="0.2.0"

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv venv --clear --python 3.14 --seed ~/nautilus-env
~/nautilus-env/bin/pip install \
    --index-url "http://${INDEX_USER}:${INDEX_PASSWORD}@${INDEX_HOST}:8080/simple/" \
    --trusted-host "$INDEX_HOST" \
    "nautilus-bridge==$VERSION"
~/nautilus-env/bin/python -c "import nautilus_bridge.backtest.runner; print('ok')"
