#!/usr/bin/env bash
# pg_dump the database through the DIRECT (non-pooled) Neon endpoint (OPS-2).
#
# Run from the instructor's laptop the day before each due date and at term end, and write the
# output to an encrypted disk. Restore with:
#
#     pg_restore --clean --no-owner --no-privileges --dbname "$DATABASE_URL_DIRECT" FILE.dump
#
# (strip the +psycopg driver from the URL first, as this script does for pg_dump).
set -euo pipefail

: "${DATABASE_URL_DIRECT:?Set DATABASE_URL_DIRECT to the direct, non-pooled Neon URL.}"

OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="$OUT_DIR/parchment-$STAMP.dump"

# pg_dump wants a libpq URL: drop the SQLAlchemy +psycopg driver suffix. sslmode in the query is
# understood by libpq and left in place.
URL="${DATABASE_URL_DIRECT/postgresql+psycopg:\/\//postgresql://}"

pg_dump --format=custom --no-owner --no-privileges --file "$FILE" "$URL"
echo "Wrote $FILE ($(du -h "$FILE" | cut -f1))"
