#!/bin/sh

# sqlite3 — the embedded-database CLI. A single binary that pulls in libsqlite3,
# readline, and ncurses; dockerize resolves and packs them all. Pairs well with
# the sidecar pattern: mount a database file and run queries against it.
#
#   docker run -i sqlite3 :memory: 'select 1 + 1;'
#   => 2

dockerize -t sqlite3 -e /usr/bin/sqlite3 /usr/bin/sqlite3
