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
# GROQ_API_KEY and PHYSIOLIVE_PASSPHRASE, then:
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
    # Generate a fresh JWT signing key so tokens survive service restarts.
    JWT_SECRET_HEX="$(openssl rand -hex 48 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(48))')"
    cat > "${ENV_FILE}" <<EOF
# PhysioLive VM environment. Edit before starting the service.
#
# --- Coach LLM ------------------------------------------------------
# GROQ_MODEL: query https://api.groq.com/openai/v1/models with your key
# to see what your account can run today. openai/gpt-oss-120b is the
# best-quality free-tier default; openai/gpt-oss-20b is faster.
COACH_PROVIDER=groq
GROQ_API_KEY=CHANGE_ME
GROQ_MODEL=openai/gpt-oss-120b

# --- Auth: passphrase route ----------------------------------------
# The web app's sign-in modal accepts this passphrase. Preferred:
# supply a bcrypt hash (starts with \$2b\$). If only the plain form is
# set the service uses it directly (fine for the first-boot smoke
# test; replace with the hash before opening the tunnel to the world).
# Generate a hash: python3 -c 'import bcrypt,sys;print(bcrypt.hashpw(sys.argv[1].encode(),bcrypt.gensalt()).decode())' 'your-passphrase'
PHYSIOLIVE_PASSPHRASE=CHANGE_ME_TO_A_LONG_PHRASE
# PHYSIOLIVE_PASSPHRASE_HASH=\$2b\$12\$...

# --- Auth: Google Sign-In route ------------------------------------
# Comma-separated list of emails allowed to sign in via Google.
# Leaving this empty disables the whitelist and rejects every Google
# sign-in. Set GOOGLE_OAUTH_CLIENT_ID to the same client id used in
# webapp/assets/config.js so ID tokens are validated against your app.
PHYSIOLIVE_ALLOWED_EMAILS=orarbeli1@gmail.com
# GOOGLE_OAUTH_CLIENT_ID=1234567890-abc.apps.googleusercontent.com

# --- Auth: JWT signing key -----------------------------------------
# Rotating this invalidates every issued token. If unset the service
# falls back to /var/lib/physiolive/jwt.secret (auto-generated).
PHYSIOLIVE_JWT_SECRET=${JWT_SECRET_HEX}
PHYSIOLIVE_JWT_TTL=604800

# --- Rate limits (documented in docs/rate-limits.md) ---------------
PHYSIOLIVE_LIMIT_PER_MIN=30/minute
PHYSIOLIVE_LIMIT_PER_DAY=500/day
PHYSIOLIVE_USER_LIMIT=20/minute

# --- Daily summary email (Gmail SMTP) ------------------------------
# Generate an App Password at https://myaccount.google.com/apppasswords
# (requires 2-Step Verification on the account first) and paste it as
# EMAIL_APP_PASSWORD below with no spaces.
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_ADDRESS=projgithub@gmail.com
EMAIL_APP_PASSWORD=CHANGE_ME_NO_SPACES
REPORT_RECIPIENT=projgithub@gmail.com

# --- Local Llama fallback (see src/vm/deploy/local-llm.md) --------
# Optional. When present the coach falls through to this model whenever
# Groq errors, times out or rate-limits, so a Groq outage no longer
# silences the coach. Leave unset to disable the fallback.
PHYSIOLIVE_LOCAL_LLM_MODEL=/opt/physiolive/models/llama-3.2-1b-instruct-q4_k_m.gguf
PHYSIOLIVE_LOCAL_LLM_CTX=1024
PHYSIOLIVE_LOCAL_LLM_THREADS=2
PHYSIOLIVE_LOCAL_LLM_MAX_TOKENS=140
EOF
    chmod 600 "${ENV_FILE}"
    chown root:root "${ENV_FILE}"
    echo "wrote ${ENV_FILE} - edit GROQ_API_KEY and PHYSIOLIVE_PASSPHRASE"
fi

echo "=== 6. build ChromaDB from the corpus ==="
if [ -d "${REPO_DIR}/corpus" ] || [ -f "${REPO_DIR}/data/corpus_seed/physio_fundamentals.json" ]; then
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
echo "  1. Edit ${ENV_FILE} - at minimum set GROQ_API_KEY and PHYSIOLIVE_PASSPHRASE."
echo "  2. (Optional) Fill GOOGLE_OAUTH_CLIENT_ID and PHYSIOLIVE_ALLOWED_EMAILS"
echo "     if you want Google Sign-In as well as the passphrase route."
echo "  3. sudo systemctl start physiolive"
echo "  4. curl http://127.0.0.1:8000/health"
echo "  5. Follow src/vm/deploy/cloudflared.md to expose the service."
echo "  6. To auto-publish the current tunnel URL to the web app, follow"
echo "     src/vm/deploy/tunnel-publisher.md and install the systemd path."
echo "=========================================="
