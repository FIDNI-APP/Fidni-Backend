#!/bin/bash

# Exit on error
set -e

echo "Deploying Django application..."

# Pull latest code
git pull

# Create directories for nginx
mkdir -p nginx/conf.d
mkdir -p nginx/ssl
mkdir -p logs

# Copy config files if they don't exist
if [ ! -f nginx/conf.d/default.conf ]; then
  cp nginx.conf nginx/conf.d/default.conf
  echo "Created Nginx configuration file"
fi

if [ ! -f .env ]; then
  cp .env.template .env
  echo "Created .env file - PLEASE UPDATE WITH PROPER VALUES"
  exit 1
fi

# Copy the production settings
if [ ! -f config/settings.py ]; then
  cp settings.py config/settings.py
  echo "Copied production settings"
fi

# Build and start containers
sudo docker-compose down
sudo docker-compose build
sudo docker-compose up -d


echo "Deployment complete!"
echo "Remember to:"
echo "1. Update your .env file with proper values"
echo "2. Update Nginx configuration with your domain"
echo "3. Set up SSL certificates"
echo "4. Change the default admin password"