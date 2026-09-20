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
FILE="$OUT_DIR/originalentry-$STAMP.dump"

# pg_dump wants a libpq URL: drop the SQLAlchemy +psycopg driver suffix. sslmode in the query is
# understood by libpq and left in place.
URL="${DATABASE_URL_DIRECT/postgresql+psycopg:\/\//postgresql://}"

# pg_dump refuses a server newer than itself, and says so in a way that is no help at 11pm the
# night before a due date. Neon upgrades its Postgres without asking, so this check earns its
# keep: find a pg_dump at least as new as the server, and say exactly what to install if none is.
SERVER_MAJOR="$(psql "$URL" -XAtc 'SHOW server_version' 2>/dev/null | cut -d. -f1)"
PG_DUMP="${PG_DUMP:-pg_dump}"
if [ -n "$SERVER_MAJOR" ]; then
  if ! "$PG_DUMP" --version | grep -qE "\b(${SERVER_MAJOR}|[0-9]{3,})\." ; then
    for candidate in /opt/homebrew/opt/postgresql@"$SERVER_MAJOR"/bin/pg_dump \
                     /usr/local/opt/postgresql@"$SERVER_MAJOR"/bin/pg_dump \
                     /usr/lib/postgresql/"$SERVER_MAJOR"/bin/pg_dump; do
      [ -x "$candidate" ] && PG_DUMP="$candidate" && break
    done
  fi
  if ! "$PG_DUMP" --version | grep -qE "\b(${SERVER_MAJOR}|[0-9]{3,})\." ; then
    echo "The database is PostgreSQL $SERVER_MAJOR; $("$PG_DUMP" --version) cannot dump it." >&2
    echo "Install matching client tools and run this again:" >&2
    echo "    brew install postgresql@$SERVER_MAJOR     # macOS" >&2
    echo "    PG_DUMP=/opt/homebrew/opt/postgresql@$SERVER_MAJOR/bin/pg_dump scripts/backup.sh" >&2
    exit 2
  fi
fi

"$PG_DUMP" --format=custom --no-owner --no-privileges --file "$FILE" "$URL"
echo "Wrote $FILE ($(du -h "$FILE" | cut -f1))"
