"""
Email Agent: Sends daily trading summary via email.
Runs at 4:15pm ET after market close.
"""
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import config


def load_trade_log() -> dict:
    """Load trade log."""
    try:
        with open(config.TRADE_LOG_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"open_positions": {}, "closed_trades": []}


def load_strategy_memory() -> dict:
    """Load strategy memory."""
    try:
        with open(config.STRATEGY_MEMORY_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"trades": [], "strategy_notes": "No trades yet.", "signal_performance": {}}


def load_watchlist() -> dict:
    """Load today's watchlist."""
    try:
        with open(config.WATCHLIST_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"watchlist": []}


def load_candidates() -> dict:
    """Load today's candidates."""
    try:
        with open(config.CANDIDATES_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"candidates": []}


def format_email_body(log: dict, memory: dict, watchlist: dict, candidates: dict) -> str:
    """Format the email body with trading summary."""
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Count today's activity
    trades_opened_today = sum(1 for pos in log["open_positions"].values() 
                              if pos.get("entry_date") == today)
    trades_closed_today = sum(1 for trade in log["closed_trades"] 
                              if trade.get("exit_date") == today)
    
    # Calculate today's P&L
    todays_pnl = sum(trade.get("pnl", 0) for trade in log["closed_trades"] 
                     if trade.get("exit_date") == today)
    
    # Build email
    body = f"""
Stock Trading Agent - Daily Summary
Date: {today}

═══════════════════════════════════════════════════════════

📊 TODAY'S ACTIVITY

Watchlist Scanned: {len(watchlist.get('watchlist', []))} stocks
Trade Candidates Found: {len(candidates.get('candidates', []))}
New Positions Opened: {trades_opened_today}
Positions Closed: {trades_closed_today}
Open Positions: {len(log['open_positions'])}

"""

    # Today's P&L
    if trades_closed_today > 0:
        body += f"\n💰 TODAY'S P&L: ${todays_pnl:,.2f}\n"
    else:
        body += "\n💰 TODAY'S P&L: No trades closed today\n"

    # Trades opened today
    if trades_opened_today > 0:
        body += "\n\n📈 TRADES OPENED TODAY:\n\n"
        for symbol, pos in log["open_positions"].items():
            if pos.get("entry_date") == today:
                body += f"  • {symbol}\n"
                body += f"    Entry: ${pos.get('entry', 0):.2f}\n"
                body += f"    Shares: {pos.get('shares', 0)}\n"
                body += f"    Stop: ${pos.get('stop_loss', 0):.2f}\n"
                body += f"    Target: ${pos.get('take_profit', 0):.2f}\n"
                body += f"    Reasoning: {pos.get('reasoning', 'N/A')}\n\n"
    
    # Trades closed today
    if trades_closed_today > 0:
        body += "\n\n📉 TRADES CLOSED TODAY:\n\n"
        for trade in log["closed_trades"]:
            if trade.get("exit_date") == today:
                pnl = trade.get("pnl", 0)
                pnl_pct = trade.get("pnl_pct", 0)
                outcome = "✅ WIN" if pnl > 0 else "❌ LOSS"
                
                body += f"  • {trade.get('symbol', 'N/A')} - {outcome}\n"
                body += f"    Entry: ${trade.get('entry_price', 0):.2f} → Exit: ${trade.get('exit_price', 0):.2f}\n"
                body += f"    P&L: ${pnl:,.2f} ({pnl_pct:.2f}%)\n"
                body += f"    Exit Reason: {trade.get('exit_reason', 'N/A')}\n\n"
    
    # Open positions
    if log["open_positions"]:
        body += "\n\n📊 CURRENT OPEN POSITIONS:\n\n"
        for symbol, pos in log["open_positions"].items():
            body += f"  • {symbol}\n"
            body += f"    Entry: ${pos.get('entry', 0):.2f} on {pos.get('entry_date', 'N/A')}\n"
            body += f"    Shares: {pos.get('shares', 0)}\n\n"
    
    # Strategy insights
    body += "\n\n🧠 WHAT I LEARNED TODAY:\n\n"
    
    # Get latest strategy notes
    strategy_notes = memory.get("strategy_notes", "No insights yet.")
    body += f"{strategy_notes}\n"
    
    # Signal performance summary
    if memory.get("signal_performance"):
        body += "\n\n📈 SIGNAL PERFORMANCE (All Time):\n\n"
        perf = memory["signal_performance"]
        # Show top 3 best performing signals
        sorted_signals = sorted(perf.items(), 
                               key=lambda x: x[1]["wins"] / (x[1]["wins"] + x[1]["losses"]) if (x[1]["wins"] + x[1]["losses"]) > 0 else 0,
                               reverse=True)[:3]
        
        for signal, stats in sorted_signals:
            total = stats["wins"] + stats["losses"]
            if total > 0:
                win_rate = (stats["wins"] / total) * 100
                body += f"  • {signal}: {stats['wins']}W / {stats['losses']}L ({win_rate:.1f}% win rate)\n"
    
    # Overall stats
    total_trades = len(memory.get("trades", []))
    if total_trades > 0:
        wins = sum(1 for t in memory["trades"] if t.get("outcome") == "win")
        win_rate = (wins / total_trades) * 100
        total_pnl = sum(t.get("pnl", 0) for t in memory["trades"])
        
        body += f"\n\n📊 OVERALL STATS:\n\n"
        body += f"  Total Trades: {total_trades}\n"
        body += f"  Win Rate: {win_rate:.1f}%\n"
        body += f"  Total P&L: ${total_pnl:,.2f}\n"
    
    body += "\n\n═══════════════════════════════════════════════════════════\n"
    body += "\nThis is an automated report from your Stock Trading Agent.\n"
    body += f"Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}\n"
    
    return body


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send email via SMTP."""
    from_email = config.EMAIL_FROM
    smtp_server = config.SMTP_SERVER
    smtp_port = config.SMTP_PORT
    smtp_user = config.SMTP_USER
    smtp_password = config.SMTP_PASSWORD
    
    if not all([from_email, smtp_server, smtp_user, smtp_password]):
        print("  Warning: Email credentials not configured in .env")
        print("  Skipping email send. Configure SMTP settings to enable email reports.")
        return False
    
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Send via SMTP
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        return True
    
    except Exception as e:
        print(f"  Error sending email: {e}")
        return False


def run():
    """Main email agent logic."""
    print(f"[{datetime.now()}] Email Agent: Generating daily summary...")
    
    # Load all data
    log = load_trade_log()
    memory = load_strategy_memory()
    watchlist = load_watchlist()
    candidates = load_candidates()
    
    # Format email
    subject = f"Stock Trading Agent - Daily Summary {datetime.now().strftime('%Y-%m-%d')}"
    body = format_email_body(log, memory, watchlist, candidates)
    
    # Send email
    to_email = config.EMAIL_TO
    
    if not to_email:
        print("  Warning: EMAIL_TO not set in config. Skipping email.")
        print("\n" + "="*60)
        print("DAILY SUMMARY (would be emailed):")
        print("="*60)
        print(body)
        print("="*60)
        return
    
    print(f"  Sending daily summary to {to_email}...")
    success = send_email(to_email, subject, body)
    
    if success:
        print(f"[{datetime.now()}] Email Agent: Daily summary sent successfully")
    else:
        print(f"[{datetime.now()}] Email Agent: Failed to send email")
        print("\n" + "="*60)
        print("DAILY SUMMARY (email failed):")
        print("="*60)
        print(body)
        print("="*60)


if __name__ == "__main__":
    run()
