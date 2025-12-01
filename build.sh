#!/bin/bash
# Build script for Render.com
# Workaround for lxml 4.9.2 build issues

set -e  # Exit on error

echo "Python version:"
python --version

echo "Installing lxml 5.3.0 (has pre-built wheels for Python 3.12)..."
# Try to install newer lxml with pre-built wheels first
pip install --only-binary :all: "lxml==5.3.0" || pip install "lxml==5.3.0" || pip install "lxml>=5.0.0"

echo "Installing other dependencies..."
# Install everything else
pip install -r requirements.txt --no-deps || true

# Install dependencies individually to handle conflicts
pip install discord.py>=2.3.0 python-dotenv>=1.0.0 beautifulsoup4>=4.9.0 aiohttp>=3.8.0 requests>=2.28.0 gunicorn>=21.2.0

# Install python-aternos and its dependencies (it will use our newer lxml)
pip install python-aternos>=2.4.0 || {
    echo "Warning: python-aternos installation had issues"
    # Try installing without strict dependency checking
    pip install python-aternos --no-deps
    pip install cloudscraper==1.2.71 Js2Py==0.74 regex==2023.6.3 websockets==11.0.3
}

echo "Build complete!"

