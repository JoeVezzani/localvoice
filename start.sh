#!/bin/bash
# LocalVoice launcher
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/.venv/bin/activate"
python3 "$DIR/localvoice.py" "$@"
