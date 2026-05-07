# Linux Setup Guide (Ubuntu)

## Auto-Start Configuration

This agent uses **systemd** (Linux's service manager) to run automatically.

### How It Works

When you run `./start.sh`, it:

1. Creates a systemd user service at `~/.config/systemd/user/stockagent.service`
2. Enables it to start automatically on login
3. Starts it immediately
4. Configures auto-restart if it crashes

### One-Time Setup

```bash
# Run once
./start.sh
```

That's it! The agent will now:
- ✅ Start automatically when you log in
- ✅ Run continuously in the background
- ✅ Execute the trading schedule every day
- ✅ Restart automatically if it crashes
- ✅ Survive system reboots (starts on next login)

### Managing the Service

**Check if running:**
```bash
systemctl --user status stockagent.service
```

**View live logs:**
```bash
journalctl --user -u stockagent.service -f
```

**View recent logs:**
```bash
journalctl --user -u stockagent.service -n 100
```

**Restart the service:**
```bash
systemctl --user restart stockagent.service
```

**Stop the service:**
```bash
./stop.sh
```

**Start again:**
```bash
./start.sh
```

### Log Files

Logs are stored at:
```
~/.local/share/stockagent/stdout.log
~/.local/share/stockagent/stderr.log
```

But it's better to use `journalctl` to view them (includes timestamps and metadata).

### Troubleshooting

**Service won't start?**
```bash
# Check for errors
journalctl --user -u stockagent.service -n 50

# Check service status
systemctl --user status stockagent.service

# Try restarting
./stop.sh
./start.sh
```

**Service not starting on login?**
```bash
# Check if enabled
systemctl --user is-enabled stockagent.service

# Should output: enabled
# If not, run:
systemctl --user enable stockagent.service
```

**Want to disable auto-start?**
```bash
systemctl --user disable stockagent.service
```

### Differences from macOS

| Feature | macOS | Linux (Ubuntu) |
|---------|-------|----------------|
| Service Manager | launchd | systemd |
| Config File | `~/Library/LaunchAgents/*.plist` | `~/.config/systemd/user/*.service` |
| Start Command | `launchctl load` | `systemctl --user start` |
| Logs | `~/Library/Logs/` | `journalctl --user` |
| Auto-start | Launch Agent | systemd user service |

### Manual Run (Without Service)

If you prefer to run manually without systemd:

```bash
source venv/bin/activate
python main.py
```

Press Ctrl+C to stop.

This is useful for testing but won't auto-start on login.
