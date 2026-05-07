#!/bin/bash
# Stop the stock trading agent

if systemctl --user is-active --quiet stockagent.service 2>/dev/null; then
    systemctl --user stop stockagent.service
    systemctl --user disable stockagent.service
    echo "Stock trading agent stopped"
else
    echo "Stock trading agent is not running"
fi
