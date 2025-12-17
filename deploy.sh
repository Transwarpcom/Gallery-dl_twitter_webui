#!/bin/bash
set -e

# Change to the script directory
cd "$(dirname "$0")"

echo "Deploying Twitter Archive WebUI..."

# 1. Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# 2. Install dependencies
echo "Installing dependencies..."
./venv/bin/pip install -r requirements.txt

# 3. Initialize Database
echo "Initializing database..."
export FLASK_APP=run.py
if [ ! -d "migrations" ]; then
    ./venv/bin/flask db init
    ./venv/bin/flask db migrate -m "Initial migration"
fi
./venv/bin/flask db upgrade

# 4. Populate Database (Initial scan)
# Warning: This can take a while if there are many files.
echo "Scanning files to populate database (this may take a while)..."
# Using --force-rescan for the first run to ensure clean state
./venv/bin/flask scan-all-users --force-rescan

# 5. Setup Systemd Service
echo "Setting up systemd service..."
SERVICE_FILE="twitter-archive.service"
TARGET_DIR="/etc/systemd/system"

if [ -f "$SERVICE_FILE" ]; then
    echo "Copying service file to $TARGET_DIR (requires sudo)..."
    sudo cp "$SERVICE_FILE" "$TARGET_DIR/"
    sudo systemctl daemon-reload
    sudo systemctl enable twitter-archive
    sudo systemctl start twitter-archive
    echo "Service started and enabled on boot."
else
    echo "Error: Service file $SERVICE_FILE not found!"
    exit 1
fi

echo "Deployment complete! Access the app at http://localhost:5000"
