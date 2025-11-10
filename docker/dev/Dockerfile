FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    curl \
    postgresql-client \
    nginx \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install gunicorn
RUN pip install gunicorn

# Copy project
COPY . .

# Set environment variables
ENV DJANGO_SETTINGS_MODULE=config.settings
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# Default environment variables (override with --env-file or -e at runtime)
ENV DEBUG=True
ENV SECRET_KEY=default-secret-key-change-in-production
ENV ALLOWED_HOSTS=*
ENV DB_ENGINE=sqlite
ENV SQLITE_PATH=/app/data/db.sqlite3
ENV DB_NAME=fidni
ENV DB_USER=postgres
ENV DB_PASSWORD=
ENV DB_HOST=localhost
ENV DB_PORT=5432

# Copy entrypoint script and nginx config
COPY entrypoint.sh /app/entrypoint.sh
COPY nginx.conf /etc/nginx/sites-available/default
RUN chmod +x /app/entrypoint.sh && \
    rm -f /etc/nginx/sites-enabled/default && \
    ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default

# Create necessary directories (data for SQLite persistence)
RUN mkdir -p /app/static /app/media /app/data /var/log/nginx /var/lib/nginx

# Create volume mount point for SQLite database
VOLUME /app/data

# Collect static files
RUN python manage.py collectstatic --noinput || true

# Expose the port nginx runs on
EXPOSE 80

CMD ["/app/entrypoint.sh"]

