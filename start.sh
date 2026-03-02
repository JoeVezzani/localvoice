#!/bin/bash
# LocalVoice launcher
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/.venv/bin/python3" -u "$DIR/localvoice.py" "$@"
