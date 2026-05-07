# Email Setup Guide

The agent sends a daily summary email at 4:15 PM ET with:
- Trades executed today
- Open positions
- P&L summary
- What the agent learned
- Signal performance stats

## Quick Setup (Gmail)

### 1. Generate Gmail App Password

Since you're using Gmail, you need an "App Password" (not your regular Gmail password):

1. Go to your Google Account: https://myaccount.google.com/
2. Click "Security" in the left menu
3. Enable "2-Step Verification" if not already enabled
4. After 2FA is enabled, go back to Security
5. Click "App passwords" (under "How you sign in to Google")
6. Select "Mail" and "Other (Custom name)"
7. Enter "Stock Trading Agent"
8. Click "Generate"
9. Copy the 16-character password (it will look like: `abcd efgh ijkl mnop`)

### 2. Update .env File

Edit `.env` and add your email settings:

```bash
# Email settings (for daily summary reports)
EMAIL_TO=aniruddhags@gmail.com
EMAIL_FROM=your_email@gmail.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=abcdefghijklmnop  # Your 16-char app password (no spaces)
```

Replace:
- `your_email@gmail.com` with your actual Gmail address
- `abcdefghijklmnop` with the app password you generated

### 3. Test Email

```bash
source venv/bin/activate
python -m agents.email_agent
```

You should receive a test email at `aniruddhags@gmail.com`.

## Alternative Email Providers

### Outlook/Hotmail

```bash
EMAIL_FROM=your_email@outlook.com
SMTP_SERVER=smtp-mail.outlook.com
SMTP_PORT=587
SMTP_USER=your_email@outlook.com
SMTP_PASSWORD=your_password
```

### Yahoo Mail

```bash
EMAIL_FROM=your_email@yahoo.com
SMTP_SERVER=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USER=your_email@yahoo.com
SMTP_PASSWORD=your_app_password  # Generate at account.yahoo.com
```

### Custom SMTP Server

```bash
EMAIL_FROM=your_email@yourdomain.com
SMTP_SERVER=smtp.yourdomain.com
SMTP_PORT=587
SMTP_USER=your_email@yourdomain.com
SMTP_PASSWORD=your_password
```

## Email Schedule

The email agent runs at **4:15 PM ET** every trading day, right before the memory agent updates at 4:30 PM.

This timing ensures:
- Market is closed (4:00 PM ET)
- All trades for the day are finalized
- You get the summary before the agent learns from today's results

## What's Included in the Email

```
Stock Trading Agent - Daily Summary
Date: 2026-05-06

📊 TODAY'S ACTIVITY
- Watchlist scanned
- Trade candidates found
- New positions opened
- Positions closed
- Current open positions

💰 TODAY'S P&L
- Total profit/loss for closed trades

📈 TRADES OPENED TODAY
- Symbol, entry price, shares, stop, target
- Reasoning for each trade

📉 TRADES CLOSED TODAY
- Symbol, entry/exit prices, P&L, exit reason

📊 CURRENT OPEN POSITIONS
- All open positions with entry details

🧠 WHAT I LEARNED TODAY
- Strategy insights from the memory agent
- Signal performance stats
- Overall win rate and total P&L
```

## Troubleshooting

**Email not sending?**

Check the logs:
```bash
journalctl --user -u stockagent.service | grep "Email Agent"
```

Common issues:

1. **"Authentication failed"**
   - Make sure you're using an App Password, not your regular Gmail password
   - Verify 2FA is enabled on your Google account

2. **"SMTP connection failed"**
   - Check your internet connection
   - Verify SMTP_SERVER and SMTP_PORT are correct
   - Some networks block port 587 - try port 465 with SSL

3. **"Email credentials not configured"**
   - Make sure all email settings are in `.env`
   - Restart the service after updating `.env`: `./stop.sh && ./start.sh`

**Test email manually:**
```bash
source venv/bin/activate
python -m agents.email_agent
```

**Disable email reports:**

If you don't want email reports, just leave the email settings blank in `.env`. The agent will print the summary to logs instead.

## Security Notes

- Never commit `.env` to git (it's in `.gitignore`)
- App passwords are safer than your main password
- You can revoke app passwords anytime from your Google account
- The agent only sends emails, it never reads your inbox
