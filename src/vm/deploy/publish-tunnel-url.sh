#!/usr/bin/env bash
# publish-tunnel-url.sh
#
# On every fresh boot of cloudflared, this script captures the new
# TryCloudflare URL from the systemd journal and pushes it into
# `webapp/tunnel-url.json` on the main branch of the PhysioLive_Product
# repo. GitHub Pages redeploys the site within a minute and users
# reload into the current tunnel automatically - no manual redeploy.
#
# The script is invoked by `publish-tunnel-url.service`, which is in
# turn triggered by `publish-tunnel-url.path` whenever
# `/var/log/cloudflared-url.txt` changes. See `tunnel-publisher.md`.
#
# Required config in `/etc/physiolive/tunnel-publisher.env` (chmod 600):
#   GITHUB_TOKEN=<fine-grained PAT with contents: read+write on this repo>
#   GITHUB_REPO=orarr2/PhysioLive_Product
#   GITHUB_BRANCH=main
#
# Read the URL from either /var/log/cloudflared-url.txt (if
# `cloudflared` writes it there) or from the last matching line in
# the systemd journal.

set -euo pipefail

CONFIG_FILE="${CONFIG_FILE:-/etc/physiolive/tunnel-publisher.env}"
URL_STATE_FILE="${URL_STATE_FILE:-/var/lib/physiolive/last-published-url}"
CLOUDFLARED_URL_FILE="${CLOUDFLARED_URL_FILE:-/var/log/cloudflared-url.txt}"

if [ ! -r "${CONFIG_FILE}" ]; then
    echo "publish-tunnel-url: ${CONFIG_FILE} not readable" >&2
    exit 1
fi
# shellcheck disable=SC1090
. "${CONFIG_FILE}"

: "${GITHUB_TOKEN:?GITHUB_TOKEN missing}"
: "${GITHUB_REPO:?GITHUB_REPO missing}"
: "${GITHUB_BRANCH:=main}"

# ---- Discover the current tunnel URL --------------------------------

find_url() {
    if [ -r "${CLOUDFLARED_URL_FILE}" ]; then
        local candidate
        candidate="$(tr -d '[:space:]' < "${CLOUDFLARED_URL_FILE}")"
        if [[ "${candidate}" =~ ^https://[a-z0-9-]+\.trycloudflare\.com$ ]]; then
            printf "%s\n" "${candidate}"
            return 0
        fi
    fi
    # Fallback: scrape the systemd journal for the most recent
    # trycloudflare hostname.
    local from_journal
    from_journal="$(journalctl -u cloudflared -n 200 --no-pager 2>/dev/null \
        | grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' \
        | tail -n 1 || true)"
    if [ -n "${from_journal}" ]; then
        printf "%s\n" "${from_journal}"
        return 0
    fi
    return 1
}

CURRENT_URL="$(find_url || true)"
if [ -z "${CURRENT_URL}" ]; then
    echo "publish-tunnel-url: no tunnel URL discovered yet" >&2
    exit 0
fi

# Idempotent: skip when the URL has not changed since last publish.
if [ -r "${URL_STATE_FILE}" ] && [ "$(cat "${URL_STATE_FILE}")" = "${CURRENT_URL}" ]; then
    echo "publish-tunnel-url: URL unchanged (${CURRENT_URL}), skipping"
    exit 0
fi

echo "publish-tunnel-url: publishing ${CURRENT_URL}"

# ---- Compose the file body ------------------------------------------

TS_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BODY_JSON="$(python3 -c 'import json,sys;print(json.dumps({"origin":sys.argv[1],"published_at":sys.argv[2],"source":"cloudflared-quick-tunnel"}, indent=2)+"\n")' "${CURRENT_URL}" "${TS_ISO}")"
CONTENT_B64="$(printf '%s' "${BODY_JSON}" | base64 -w 0)"

PATH_IN_REPO="webapp/tunnel-url.json"
API="https://api.github.com/repos/${GITHUB_REPO}/contents/${PATH_IN_REPO}"

# ---- Fetch the current SHA (if the file already exists) -------------

EXISTING_SHA="$(curl -sS -H "Authorization: Bearer ${GITHUB_TOKEN}" \
                     -H "Accept: application/vnd.github+json" \
                     "${API}?ref=${GITHUB_BRANCH}" \
                | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("sha",""))' \
                2>/dev/null || true)"

# ---- Compose the PUT payload ----------------------------------------

PAYLOAD_FILE="$(mktemp)"
trap 'rm -f "${PAYLOAD_FILE}"' EXIT
python3 - "${CURRENT_URL}" "${CONTENT_B64}" "${GITHUB_BRANCH}" "${EXISTING_SHA}" >"${PAYLOAD_FILE}" <<'PY'
import json, sys
url, content_b64, branch, sha = sys.argv[1:5]
payload = {
    "message": f"Web app: point at fresh tunnel URL {url}",
    "content": content_b64,
    "branch": branch,
}
if sha:
    payload["sha"] = sha
print(json.dumps(payload))
PY

# ---- Publish -------------------------------------------------------

HTTP_STATUS="$(curl -sS -o /tmp/publish-tunnel-response.json -w '%{http_code}' \
    -X PUT \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "Content-Type: application/json" \
    --data "@${PAYLOAD_FILE}" \
    "${API}")"

if [ "${HTTP_STATUS}" != "200" ] && [ "${HTTP_STATUS}" != "201" ]; then
    echo "publish-tunnel-url: GitHub API returned ${HTTP_STATUS}" >&2
    cat /tmp/publish-tunnel-response.json >&2
    exit 1
fi

mkdir -p "$(dirname "${URL_STATE_FILE}")"
printf '%s\n' "${CURRENT_URL}" > "${URL_STATE_FILE}"
echo "publish-tunnel-url: published ${CURRENT_URL}"
