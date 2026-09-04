#!/usr/bin/env bash
# One-time setup for the nightly DB backup. Requires /mnt/backup already
# mounted and /opt/stories already provisioned.
# Usage: sudo ./install-backup.sh
set -euo pipefail

DEPLOY_USER="${SUDO_USER:-$(logname)}"
script_dir=$(dirname "$(readlink -f "$0")")

install -m 0755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$script_dir/backup.sh" /opt/stories/backup.sh

sed "s/^User=.*/User=$DEPLOY_USER/" "$script_dir/story-backup.service" > /etc/systemd/system/story-backup.service
cp "$script_dir/story-backup.timer" /etc/systemd/system/story-backup.timer

systemctl daemon-reload
systemctl enable --now story-backup.timer

echo "Installed. Next run: $(systemctl list-timers story-backup.timer --no-legend | awk '{print $1, $2}')"
