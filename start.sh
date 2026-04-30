#!/bin/bash
# LocalVoice launcher — upgraded to large-v3-turbo Apr 21 2026
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/.venv/bin/python3" -u "$DIR/localvoice.py" --model large "$@"
