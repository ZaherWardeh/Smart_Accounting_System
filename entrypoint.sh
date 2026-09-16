#!/bin/sh
set -e

# On a host with a persistent volume (SQLITE_DATA_DIR set, e.g. Fly.io's
# /data mount), seed it from the accounting.db baked into this image the
# first time the volume is empty, so the deployed app starts with this
# repo's chart of accounts already in place instead of a blank database.
# Later boots see the file already there and leave it alone - the volume,
# not the image, is the source of truth from then on.
if [ -n "$SQLITE_DATA_DIR" ]; then
    mkdir -p "$SQLITE_DATA_DIR"
    if [ ! -f "$SQLITE_DATA_DIR/accounting.db" ]; then
        cp /app/accounting.db "$SQLITE_DATA_DIR/accounting.db"
        echo "Seeded $SQLITE_DATA_DIR/accounting.db from the image's bundled accounting.db"
    fi
fi

exec uvicorn main:app --host 0.0.0.0 --port 8000
