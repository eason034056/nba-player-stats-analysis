#!/bin/sh
# Apply the numbered SQL files, then replace this process with the server.
# set -e: a failed upgrade must not start uvicorn.
set -e
python -m app.migrations upgrade
exec "$@"
