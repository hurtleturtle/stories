#!/usr/bin/env bash
# One-time setup for a fresh host. Idempotent - safe to re-run.
# Usage: scp deploy/* <host>:/tmp/ && ssh <host> sudo /tmp/provision.sh
set -euo pipefail

if ! command -v docker >/dev/null; then
    echo "Installing Docker Engine..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    arch=$(dpkg --print-architecture)
    codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
    echo "deb [arch=$arch signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $codename stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

systemctl enable --now docker

DEPLOY_USER="${SUDO_USER:-$(logname)}"
usermod -aG docker "$DEPLOY_USER"

mkdir -p /opt/stories
# Owned by the deploy user, not root: they're in the docker group, which is
# already root-equivalent (it can mount the host fs via a container), so a
# root-owned directory buys no real isolation - it only forces `sudo docker`,
# which reads root's own (unauthenticated) registry config instead of theirs.
chown "$DEPLOY_USER:$DEPLOY_USER" /opt/stories
chmod 700 /opt/stories

script_dir=$(dirname "$(readlink -f "$0")")
cp "$script_dir/compose.yaml" "$script_dir/deploy.sh" "$script_dir/autodeploy.sh" "$script_dir/prune.sh" /opt/stories/
chown "$DEPLOY_USER:$DEPLOY_USER" /opt/stories/compose.yaml /opt/stories/deploy.sh /opt/stories/autodeploy.sh /opt/stories/prune.sh
chmod +x /opt/stories/deploy.sh /opt/stories/autodeploy.sh /opt/stories/prune.sh

sed "s/^User=.*/User=$DEPLOY_USER/" "$script_dir/story-autodeploy.service" > /etc/systemd/system/story-autodeploy.service
cp "$script_dir/story-autodeploy.timer" /etc/systemd/system/story-autodeploy.timer
sed "s/^User=.*/User=$DEPLOY_USER/" "$script_dir/story-prune.service" > /etc/systemd/system/story-prune.service
cp "$script_dir/story-prune.timer" /etc/systemd/system/story-prune.timer
systemctl daemon-reload
systemctl enable --now story-autodeploy.timer story-prune.timer

if [ ! -f /opt/stories/.env ]; then
    cp "$script_dir/env.example" /opt/stories/.env
    chown "$DEPLOY_USER:$DEPLOY_USER" /opt/stories/.env
    chmod 600 /opt/stories/.env
    echo "Wrote /opt/stories/.env from the example - fill it in before deploying."
fi

echo "Done. Log out/in for the docker group to take effect, then fill in /opt/stories/.env."
echo "Run /opt/stories/deploy.sh as $DEPLOY_USER, not root - sudo would use root's own docker login instead."
echo "story-autodeploy.timer is now polling APP_TAG every 5min - pin it to a version to pause auto-deploy."
