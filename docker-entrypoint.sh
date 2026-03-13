#!/bin/sh
set -eu

mkdir -p /app/data /app/static/uploads

python database.py

exec gunicorn --bind "0.0.0.0:${PORT:-8000}" app:app
