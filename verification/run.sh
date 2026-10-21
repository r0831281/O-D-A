#!/bin/sh
set -eu
umask 077
mkdir -p "$HOME"
unset PYTHONPATH
ruff check --no-cache /app/src /app/tests /app/verification
ruff format --check --no-cache /app/src /app/tests /app/verification
python -I /app/verification/verify_package.py
