#!/bin/bash
set -e

# Wait for database (only if using PostgreSQL)
if [ -n "$DB_ENGINE" ] && [ "$DB_ENGINE" != "django.db.backends.sqlite3" ]; then
  echo "Waiting for PostgreSQL database..."
  while ! pg_isready -h ${DB_HOST:-db} -p ${DB_PORT:-5432} -U ${DB_USER:-postgres}; do
    sleep 1
  done
  echo "Database available"
else
  echo "Using SQLite database (no wait needed)"
fi

# Run migrations
python manage.py migrate --noinput

python ./tests/base_tables.py
# Collect static files
python manage.py collectstatic --noinput

# Start gunicorn
exec gunicorn --bind 0.0.0.0:8000 --workers 4 --timeout 120 --access-logfile - --error-logfile - config.wsgi:application
