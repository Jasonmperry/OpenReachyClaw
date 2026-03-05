#!/bin/bash
# Deploy OpenReachyClaw to Jetson
# Usage: ./deploy.sh [--dry-run]

set -e

JETSON="jetson@192.168.2.2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

RSYNC_OPTS="-avz --exclude __pycache__"
if [[ "$1" == "--dry-run" ]]; then
    RSYNC_OPTS="$RSYNC_OPTS --dry-run"
    echo "=== DRY RUN — no files will be transferred ==="
fi

echo "--- Deploying tools to ~/rosie_tools/ ---"
rsync $RSYNC_OPTS \
    --exclude notify.py \
    "$SCRIPT_DIR/openreachyclaw/tools/" \
    "$JETSON:~/rosie_tools/"

echo ""
echo "--- Deploying static UI to conversation app ---"
rsync $RSYNC_OPTS \
    "$SCRIPT_DIR/static/" \
    "$JETSON:~/reachy_mini_conversation_app/src/reachy_mini_conversation_app/static/"

echo ""
echo "--- Deploying openreachyclaw package ---"
rsync $RSYNC_OPTS \
    "$SCRIPT_DIR/openreachyclaw/" \
    "$JETSON:~/OpenReachyClaw/openreachyclaw/"

echo ""
echo "--- Deploying profiles ---"
rsync $RSYNC_OPTS \
    "$SCRIPT_DIR/profiles/" \
    "$JETSON:~/OpenReachyClaw/profiles/"

echo ""
echo "Deploy complete. Restart Rosie on Jetson to pick up changes."
echo "  ssh $JETSON"
echo "  cd ~/OpenReachyClaw && ./start_rosie.sh"
