#!/bin/bash
# One-time setup script for Linux

set -e

echo "Stock Trading Agent - Setup (Linux)"
echo "===================================="
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Please install Python 3.11+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "✓ Python version: $PYTHON_VERSION"

# Create virtual environment
echo ""
echo "Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate and install dependencies
echo ""
echo "Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create data directory
echo ""
echo "Creating data directory..."
mkdir -p data

# Create log directory
echo ""
echo "Creating log directory..."
mkdir -p ~/.local/share/stockagent

# Check for required env vars
echo ""
echo "Checking environment variables..."
if [ ! -f .env ]; then
    echo "Warning: .env file not found"
    exit 1
fi

source .env

if [ -z "$APCA_API_KEY_ID" ]; then
    echo "Error: APCA_API_KEY_ID not set in .env"
    exit 1
fi

if [ -z "$APCA_API_SECRET_KEY" ]; then
    echo "Error: APCA_API_SECRET_KEY not set in .env"
    exit 1
fi

echo "✓ Alpaca API keys configured"

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "Warning: ANTHROPIC_API_KEY not set (optional but recommended)"
else
    echo "✓ Anthropic API key configured"
fi

echo ""
echo "===================================="
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Test manually: source venv/bin/activate && python main.py"
echo "  2. Start service: ./start.sh"
echo "  3. View logs: journalctl --user -u stockagent.service -f"
echo ""
