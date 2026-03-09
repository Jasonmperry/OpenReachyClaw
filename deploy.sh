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
    --exclude send_notification.py \
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
echo "--- Deploying patch script ---"
scp -q "$SCRIPT_DIR/patch_console.py" "$JETSON:~/OpenReachyClaw/patch_console.py"

if [[ "$1" != "--dry-run" ]]; then
    echo ""
    echo "--- Patching control routes into conversation app ---"
    ssh "$JETSON" "cd ~/OpenReachyClaw && python3 patch_console.py"

    echo ""
    echo "--- Restarting Rosie ---"
    # Kill existing conversation app (but leave the daemon running)
    ssh "$JETSON" "pkill -f 'reachy_mini_conversation_app.main' 2>/dev/null || true"
    sleep 2
    # Start the conversation app in the background
    ssh "$JETSON" "bash -c 'cd ~/reachy_mini_conversation_app && source ~/miniforge3/bin/activate rosie && nohup python3 -m reachy_mini_conversation_app.main > /tmp/rosie-conversation.log 2>&1 &'"
    echo "Rosie restarted. Give it ~10 seconds to fully initialize."
    echo "  Web UI: http://192.168.2.2:7860"
fi

echo ""
echo "Deploy complete."
