#!/bin/sh
set -e

run_if_enabled() {
    flag_name="$1"
    shift
    flag_value="$(printenv "$flag_name" || true)"
    if [ "$flag_value" = "1" ] || [ "$flag_value" = "true" ] || [ "$flag_value" = "True" ]; then
        "$@"
    fi
}

run_if_enabled DJANGO_RUN_MIGRATIONS python manage.py migrate --noinput
run_if_enabled DJANGO_COLLECTSTATIC python manage.py collectstatic --noinput
run_if_enabled DJANGO_SEED_DEMO_DATA python manage.py seed_demo_data

exec python manage.py runserver 0.0.0.0:8000
