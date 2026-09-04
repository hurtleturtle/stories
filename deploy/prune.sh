#!/usr/bin/env bash
# Remove unused Docker images older than 24h. Run by story-prune.timer.
#
# "Unused" = not referenced by any container (running or stopped) - that's
# the only notion of "in use" Docker tracks for images. "until=24h" filters
# on image creation time, not last-pulled/last-used time (Docker doesn't
# track that), so a still-referenced image is never touched regardless of age.
set -euo pipefail

docker image prune -a -f --filter "until=24h"
