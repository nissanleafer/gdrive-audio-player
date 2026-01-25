#!/bin/bash
# Setup script for Google Drive Audio Player

echo "🎵 Google Drive Audio Player - Setup"
echo "====================================="

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not found."
    echo "   Install from https://www.python.org/downloads/"
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate and install dependencies
echo "📦 Installing dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "   1. Set up Google Cloud credentials (one-time):"
echo "      - Go to https://console.cloud.google.com/"
echo "      - Create a project and enable Google Drive API"
echo "      - Create OAuth credentials (Desktop app)"
echo "      - Download and save as 'credentials.json' in this folder"
echo ""
echo "   2. Run the player:"
echo "      source venv/bin/activate"
echo "      python3 gdrive_player.py"
echo ""
