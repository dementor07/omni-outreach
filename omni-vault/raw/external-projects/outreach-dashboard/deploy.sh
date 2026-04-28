#!/bin/bash
# Deploy outreach-dashboard to server via git pull
SERVER="root@193.203.161.15"
REMOTE="/home/omni/outreach-dashboard"

echo "Deploying dashboard to server..."

# Push local branch to origin
git push origin dashboard

# Sync .env to server
scp .env "$SERVER:$REMOTE/.env"

# Pull on server (stash local changes, pull, restore)
ssh "$SERVER" "cd $REMOTE && git stash && git pull origin dashboard && git stash pop 2>/dev/null; echo pulled"

# Restart service
ssh "$SERVER" "systemctl restart outreach-dashboard && sleep 2 && systemctl is-active outreach-dashboard"

echo "Done."
