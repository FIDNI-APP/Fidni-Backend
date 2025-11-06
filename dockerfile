FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    curl \
    postgresql-client \
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

# Create a non-root user to run the app
RUN adduser --disabled-password --gecos "" appuser

# Copy entrypoint script before changing user
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create necessary directories and set permissions
RUN mkdir -p /app/static /app/media /app/data && \
    chown -R appuser:appuser /app

# Collect static files
RUN python manage.py collectstatic --noinput || true

USER appuser

# Expose the port the app runs on
EXPOSE 8000

CMD ["/app/entrypoint.sh"]

