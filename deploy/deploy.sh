#!/usr/bin/env bash
# Usage: ./deploy.sh v1.2.3
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <tag>" >&2
    exit 1
fi

cd "$(dirname "$(readlink -f "$0")")"
sed -i "s/^APP_TAG=.*/APP_TAG=$1/" .env

docker compose pull api worker frontend
docker compose run --rm api alembic upgrade head
docker compose up -d
docker compose ps
