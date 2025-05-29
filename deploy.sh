#!/bin/bash

# Exit on error
set -e

echo "Deploying Django application..."

# Allow git to trust this directory
git config --global --add safe.directory /home/ec2-user/Fidni-Backend

# Pull latest code
git pull

# Create directories for nginx
mkdir -p nginx/conf.d
mkdir -p nginx/ssl
mkdir -p logs

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
