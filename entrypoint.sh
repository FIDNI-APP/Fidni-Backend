#!/bin/bash
set -e

# Wait for database (only if using PostgreSQL on non-proxy hosts)
if [ -n "$DB_ENGINE" ] && [ "$DB_ENGINE" = "postgresql" ]; then
  # Skip pg_isready for Railway proxy hosts
  if [[ "$DB_HOST" != *"railway"* ]] && [[ "$DB_HOST" != *"proxy"* ]]; then
    echo "Waiting for PostgreSQL database at $DB_HOST:$DB_PORT..."
    timeout=30
    elapsed=0
    while ! pg_isready -h ${DB_HOST:-db} -p ${DB_PORT:-5432} -U ${DB_USER:-postgres} 2>/dev/null; do
      sleep 1
      elapsed=$((elapsed + 1))
      if [ $elapsed -ge $timeout ]; then
        echo "Database connection timeout, proceeding anyway..."
        break
      fi
    done
    echo "Database available"
  else
    echo "Using Railway/proxy database (skipping pg_isready check)"
  fi
fi

# Run migrations
python manage.py migrate --noinput

python ./tests/base_tables.py
# Collect static files
python manage.py collectstatic --noinput

# Start nginx
nginx

# Start gunicorn (bind to localhost only, nginx will proxy)
# Workers: 2*CPU+1 (adjust based on your server CPUs)
exec gunicorn --bind 127.0.0.1:8000 --workers 9 --worker-class sync --timeout 120 --max-requests 1000 --max-requests-jitter 50 --access-logfile - --error-logfile - config.wsgi:application
