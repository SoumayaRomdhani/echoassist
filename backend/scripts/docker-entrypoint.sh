#!/bin/sh
# Seed the docs directory from the baked demo set when it is empty (i.e. a freshly
# mounted persistent volume), so uploaded documents survive a rebuild WITHOUT the
# volume masking the bundled demo documents. No-op once the volume has content.
set -e

if [ -d /app/data/docs.seed ] && [ -z "$(ls -A /app/data/docs 2>/dev/null)" ]; then
  echo "docker-entrypoint: seeding demo documents into /app/data/docs"
  mkdir -p /app/data/docs
  cp -r /app/data/docs.seed/. /app/data/docs/
fi

exec "$@"
