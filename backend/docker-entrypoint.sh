#!/bin/sh
# Apply migrations before starting the web process or the worker. The worker waits for the
# backend's healthcheck, so it normally finds the schema already current. Running Alembic
# here is idempotent; a future multi-replica deployment moves this to a one-shot job.
set -eu

alembic upgrade head
exec "$@"
