#!/usr/bin/env bash
# One-shot installer for the PhysioLive VM service on a fresh Debian VM.
# Run as: sudo bash setup.sh
#
# What it does:
#   1. Installs the apt packages the FastAPI service needs.
#   2. Creates the `physiolive` service user and its dirs.
#   3. Clones (or pulls) the repo into /opt/physiolive/repo.
#   4. Creates a Python venv and installs src/vm/requirements.txt.
#   5. Seeds /etc/physiolive/env with placeholders (edit before starting).
#   6. Builds the ChromaDB index from the seed corpus.
#   7. Installs the systemd unit and enables it.
#   8. Configures a basic ufw firewall (SSH-only inbound).
#
# After this script finishes, edit /etc/physiolive/env with your real
# GROQ_API_KEY and PHYSIOLIVE_API_TOKEN, then:
#   sudo systemctl start physiolive
#   curl http://127.0.0.1:8000/health

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/orarr2/PhysioLive_Product.git}"
REPO_DIR="/opt/physiolive/repo"
VENV_DIR="/opt/physiolive/venv"
ENV_FILE="/etc/physiolive/env"

if [ "$(id -u)" -ne 0 ]; then
    echo "run this script with sudo" >&2
    exit 1
fi

echo "=== 1. apt install ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    python3-full python3-pip python3-venv \
    sqlite3 git curl ca-certificates ufw

echo "=== 2. service user + dirs ==="
id -u physiolive >/dev/null 2>&1 || useradd -r -s /bin/false -d /opt/physiolive physiolive
mkdir -p /opt/physiolive /var/lib/physiolive /etc/physiolive
chown -R physiolive:physiolive /opt/physiolive /var/lib/physiolive
chmod 750 /etc/physiolive

echo "=== 3. clone or pull repo ==="
if [ ! -d "${REPO_DIR}/.git" ]; then
    sudo -u physiolive git clone --depth=1 "${REPO_URL}" "${REPO_DIR}"
else
    sudo -u physiolive git -C "${REPO_DIR}" pull --ff-only
fi

echo "=== 4. venv + deps ==="
if [ ! -d "${VENV_DIR}" ]; then
    sudo -u physiolive python3 -m venv "${VENV_DIR}"
fi
sudo -u physiolive "${VENV_DIR}/bin/pip" install --upgrade pip wheel
sudo -u physiolive "${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/src/vm/requirements.txt"

echo "=== 5. env placeholders ==="
if [ ! -f "${ENV_FILE}" ]; then
    cat > "${ENV_FILE}" <<'EOF'
# PhysioLive VM environment. Edit before starting the service.
# GROQ_MODEL: query https://api.groq.com/openai/v1/models with your key
# to see what your account can run today (Groq's catalog changes over time).
# openai/gpt-oss-20b is a safe generalist default across free-tier keys.
COACH_PROVIDER=groq
GROQ_API_KEY=CHANGE_ME
GROQ_MODEL=openai/gpt-oss-20b
PHYSIOLIVE_API_TOKEN=CHANGE_ME
EOF
    chmod 600 "${ENV_FILE}"
    chown root:root "${ENV_FILE}"
    echo "wrote ${ENV_FILE} - edit it and set the real values"
fi

echo "=== 6. build ChromaDB from seed corpus ==="
if [ -f "${REPO_DIR}/data/corpus_seed/physio_fundamentals.json" ]; then
    sudo -u physiolive bash -c "cd ${REPO_DIR}/src && PYTHONPATH=${REPO_DIR}/src ${VENV_DIR}/bin/python -m app.tools.build_index" || \
        echo "corpus build failed - you can rerun it later"
fi

echo "=== 7. systemd unit ==="
install -m 644 "${REPO_DIR}/src/vm/deploy/physiolive.service" /etc/systemd/system/physiolive.service
systemctl daemon-reload
systemctl enable physiolive.service

echo "=== 8. firewall ==="
ufw --force default deny incoming
ufw --force default allow outgoing
ufw allow OpenSSH
# Cloudflare Tunnel is outbound-only so nothing else needs opening.
ufw --force enable

echo
echo "=========================================="
echo "PhysioLive VM setup complete."
echo
echo "Next steps:"
echo "  1. Edit ${ENV_FILE} with your GROQ_API_KEY and PHYSIOLIVE_API_TOKEN."
echo "  2. sudo systemctl start physiolive"
echo "  3. curl http://127.0.0.1:8000/health"
echo "  4. Follow src/vm/deploy/cloudflared.md to expose the service."
echo "=========================================="
