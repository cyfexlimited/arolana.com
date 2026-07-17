#!/usr/bin/env bash

set -u

if [ "${PROJECT_VIDEO_WORKER_ENABLED:-true}" = "true" ]; then
    (
        while true; do
            python manage.py process_project_videos \
                --limit "${PROJECT_VIDEO_WORKER_BATCH_SIZE:-1}" || true
            sleep "${PROJECT_VIDEO_WORKER_INTERVAL_SECONDS:-45}"
        done
    ) &
fi

exec gunicorn arolana_config.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --threads 4 \
    --worker-class gthread \
    --timeout 90 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile -
