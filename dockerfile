FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
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

# Create directory for SQLite database
RUN mkdir -p /app/data

# Create a non-root user to run the app
RUN adduser --disabled-password --gecos "" appuser

# Create necessary directories and set permissions
RUN mkdir -p /app/static /app/media /app/data && \
    chown -R appuser:appuser /app

USER appuser

# Run migrations and collect static files
RUN python manage.py makemigrations && \
    python manage.py migrate && \
    python ./tests/base_tables.py && \
    python manage.py collectstatic --noinput

# Expose the port the app runs on   
EXPOSE 8000

# Start Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120", "config.wsgi:application"]