#!/usr/bin/env bash

set -u

exec gunicorn arolana_config.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
