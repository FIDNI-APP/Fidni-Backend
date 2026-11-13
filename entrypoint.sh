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

# WebSocket de la messagerie et des appels (13/11/2026) : uvicorn, un seul processus, relancé s'il s'arrête.
# Il ne sert que /ws/ (nginx) ; gunicorn et lui se parlent par Redis (REDIS_URL).
(
  while true; do
    uvicorn config.asgi:application --host 127.0.0.1 --port 8001 --proxy-headers --ws-ping-interval 20 \
      --ws-ping-timeout 20 --no-access-log --log-level warning || true
    echo "uvicorn arrêté, relance dans 2 s"
    sleep 2
  done
) &

# Start gunicorn (bind to localhost only, nginx will proxy)
# Workers default to 3 (fine for a laptop / small VPS). Override with
# GUNICORN_WORKERS in the environment; rule of thumb on a real server: 2*CPU+1.
exec gunicorn --bind 127.0.0.1:8000 --workers "${GUNICORN_WORKERS:-3}" --worker-class sync --timeout 120 --max-requests 1000 --max-requests-jitter 50 --access-logfile - --error-logfile - config.wsgi:application
