#!/bin/bash
# Start the stock trading agent

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SERVICE_FILE="$HOME/.config/systemd/user/stockagent.service"

# Check if already running
if systemctl --user is-active --quiet stockagent.service 2>/dev/null; then
    echo "Stock agent is already running"
    systemctl --user status stockagent.service
    exit 0
fi

# Create systemd user directory if it doesn't exist
mkdir -p "$HOME/.config/systemd/user"

# Create systemd service file
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Stock Trading Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/main.py
Restart=always
RestartSec=10
StandardOutput=append:$HOME/.local/share/stockagent/stdout.log
StandardError=append:$HOME/.local/share/stockagent/stderr.log

[Install]
WantedBy=default.target
EOF

# Create log directory
mkdir -p "$HOME/.local/share/stockagent"

# Reload systemd, enable and start the service
systemctl --user daemon-reload
systemctl --user enable stockagent.service
systemctl --user start stockagent.service

echo "Stock trading agent started"
echo "Logs: $HOME/.local/share/stockagent/"
echo ""
echo "Commands:"
echo "  Status:  systemctl --user status stockagent.service"
echo "  Logs:    journalctl --user -u stockagent.service -f"
echo "  Stop:    ./stop.sh"
