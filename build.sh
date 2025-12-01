#!/bin/bash
# Build script for Render.com
# Python 3.11 should work with all dependencies

echo "Python version:"
python --version

echo "Installing all dependencies..."
# Install everything normally - Python 3.11 should work with lxml 4.9.2 and js2py 0.74
pip install -r requirements.txt

echo "Build complete!"

