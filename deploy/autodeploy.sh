#!/usr/bin/env bash
# Deploy whatever APP_TAG now points at, if it changed. Run by story-autodeploy.timer.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

# registry digest as the trigger - the GitHub API knows nothing docker pull doesn't.
tag=$(sed -n 's/^APP_TAG=//p' .env)
[ -n "$tag" ] || exit 0        # host not configured yet

changed=0
for svc in api worker frontend; do
    img="ghcr.io/hurtleturtle/stories-$svc:$tag"
    before=$(docker image inspect -f '{{.Id}}' "$img" 2>/dev/null || true)
    docker pull -q "$img" >/dev/null
    [ "$before" = "$(docker image inspect -f '{{.Id}}' "$img")" ] || changed=1
done

[ "$changed" -eq 1 ] || exit 0
./deploy.sh "$tag"
