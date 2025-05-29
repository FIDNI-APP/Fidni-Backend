#!/bin/bash
set -e

# Wait for PostgreSQL to be ready (optional)
# You can use wait-for-it.sh or similar tools here

echo "Running migrations..."
python manage.py makemigrations --noinput
python manage.py migrate --noinput

echo "Running base table init..."
python ./tests/base_tables.py

echo "Collecting static files..."
python manage.py collectstatic --noinput

exec "$@"
