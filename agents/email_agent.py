"""
Email Agent: Sends daily intraday trading summary via email.
Runs at 4:15 PM ET after market close and force-close.
"""
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
import config
from logger import get_logger

log = get_logger("email")

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_trade_log() -> dict:
    try:
        with open(config.TRADE_LOG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"open_positions": {}, "closed_trades": []}


def load_strategy_memory() -> dict:
    try:
        with open(config.STRATEGY_MEMORY_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"trades": [], "strategy_notes": "No trades yet.", "signal_performance": {}}


def load_intraday_watchlist() -> dict:
    try:
        with open(config.INTRADAY_WATCHLIST_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"stocks": [], "count": 0}


def load_candidates() -> dict:
    try:
        with open(config.CANDIDATES_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"candidates": []}


# ---------------------------------------------------------------------------
# Email formatting
# ---------------------------------------------------------------------------

def format_email_body(
    trade_log: dict,
    memory: dict,
    intraday_watchlist: dict,
    candidates: dict,
) -> str:
    today = datetime.now(tz=ET).strftime("%Y-%m-%d")

    # Today's closed trades
    todays_closed = [
        t for t in trade_log["closed_trades"]
        if t.get("exit_date") == today
    ]

    # P&L — only count trades that have actual pnl recorded
    todays_pnl = sum(t.get("pnl", 0) for t in todays_closed)
    wins_today = sum(1 for t in todays_closed if t.get("outcome") == "win")
    losses_today = sum(1 for t in todays_closed if t.get("outcome") == "loss")

    # In-play stocks today
    inplay_stocks = intraday_watchlist.get("stocks", [])
    inplay_symbols = [s["symbol"] for s in inplay_stocks]

    # Setup type breakdown for today's closed trades
    vwap_trades = [t for t in todays_closed if t.get("setup_type", "vwap_reclaim") == "vwap_reclaim"]
    orb_trades = [t for t in todays_closed if t.get("setup_type") == "orb"]

    body = f"""
Day Trading Agent — Daily Summary
Date: {today}

═══════════════════════════════════════════════════════════

📊 TODAY'S ACTIVITY

In-Play Stocks Scanned: {len(inplay_symbols)} ({', '.join(inplay_symbols) or 'none'})
Setups Found: {len(candidates.get('candidates', []))} (VWAP Reclaim: {sum(1 for c in candidates.get('candidates', []) if c.get('setup_type', 'vwap_reclaim') == 'vwap_reclaim')}, ORB: {sum(1 for c in candidates.get('candidates', []) if c.get('setup_type') == 'orb')})
Trades Closed Today: {len(todays_closed)} (VWAP Reclaim: {len(vwap_trades)}, ORB: {len(orb_trades)})
"""

    if todays_closed:
        win_rate_today = (wins_today / len(todays_closed) * 100) if todays_closed else 0
        body += f"  Wins: {wins_today}  |  Losses: {losses_today}  |  Win Rate: {win_rate_today:.0f}%\n"

    # Today's P&L
    if todays_closed:
        pnl_emoji = "💰" if todays_pnl >= 0 else "🔴"
        body += f"\n{pnl_emoji} TODAY'S P&L: ${todays_pnl:,.2f}"
        # Per-strategy P&L breakdown
        vwap_pnl = sum(t.get("pnl", 0) for t in vwap_trades)
        orb_pnl = sum(t.get("pnl", 0) for t in orb_trades)
        if vwap_trades and orb_trades:
            body += f"  (VWAP Reclaim: ${vwap_pnl:,.2f} | ORB: ${orb_pnl:,.2f})"
        elif vwap_trades:
            body += f"  (VWAP Reclaim)"
        elif orb_trades:
            body += f"  (ORB Breakout)"
        body += "\n"
    else:
        body += "\n💤 TODAY'S P&L: No trades today\n"

    # Trades closed today — detailed
    if todays_closed:
        body += "\n\n📋 TRADES CLOSED TODAY:\n\n"
        for trade in todays_closed:
            pnl = trade.get("pnl", 0)
            outcome = trade.get("outcome", "unknown")
            if outcome == "win":
                outcome_icon = "✅ WIN"
            elif outcome == "loss":
                outcome_icon = "❌ LOSS"
            else:
                outcome_icon = "⏹ CLOSED"

            entry_price = trade.get("entry_price", trade.get("entry", 0))
            exit_price = trade.get("exit_price", 0)
            pnl_pct = trade.get("pnl_pct", 0)

            setup_type = trade.get("setup_type", "vwap_reclaim")
            setup_label = setup_type.upper().replace("_", " ")

            body += f"  • {trade.get('symbol', '?')} [{setup_label}] — {outcome_icon}\n"
            body += f"    Entry: ${entry_price:.2f} at {trade.get('entry_time', '?')}\n"
            if exit_price:
                body += f"    Exit:  ${exit_price:.2f} at {trade.get('exit_time', '?')}\n"
            if pnl:
                body += f"    P&L:   ${pnl:,.2f}"
                if pnl_pct:
                    body += f" ({pnl_pct:.2f}%)"
                body += "\n"
            body += f"    Exit Reason: {trade.get('exit_reason', 'N/A')}\n"

            # Show key signals at entry
            signals = trade.get("signals_at_entry", {})
            if signals:
                fired = [
                    name for name, data in signals.items()
                    if isinstance(data, dict) and data.get("points", 0) > 0
                ]
                if fired:
                    body += f"    Signals: {', '.join(fired)}\n"

            # Intraday context
            gap = trade.get("gap_pct")
            vol_ratio = trade.get("open_vol_ratio")
            vwap = trade.get("vwap_at_entry")
            if gap is not None:
                body += f"    Gap: {gap:+.2f}%"
                if vol_ratio is not None:
                    body += f"  |  Opening Vol: {vol_ratio:.1f}x avg"
                if vwap is not None:
                    body += f"  |  VWAP at entry: ${vwap:.2f}"
                body += "\n"

            reasoning = trade.get("reasoning", "")
            if reasoning:
                body += f"    Note: {reasoning[:120]}\n"
            body += "\n"

    # Any positions still open (shouldn't happen after force close, but just in case)
    if trade_log["open_positions"]:
        body += "\n⚠️  POSITIONS STILL OPEN (force close may have failed):\n\n"
        for symbol, pos in trade_log["open_positions"].items():
            body += f"  • {symbol} — {pos.get('shares', 0)} shares @ ${pos.get('entry', 0):.2f}\n"
            body += f"    Entered: {pos.get('entry_date', '?')} {pos.get('entry_time', '')}\n\n"

    # Strategy insights from memory
    body += "\n\n🧠 STRATEGY INSIGHTS:\n\n"
    strategy_notes = memory.get("strategy_notes", "No insights yet.")
    body += f"{strategy_notes}\n"

    # Signal performance
    if memory.get("signal_performance"):
        body += "\n\n📈 SIGNAL PERFORMANCE (All Time):\n\n"
        perf = memory["signal_performance"]
        sorted_signals = sorted(
            perf.items(),
            key=lambda x: (
                x[1]["wins"] / (x[1]["wins"] + x[1]["losses"])
                if (x[1]["wins"] + x[1]["losses"]) > 0 else 0
            ),
            reverse=True,
        )[:5]

        for signal, stats in sorted_signals:
            total = stats["wins"] + stats["losses"]
            if total > 0:
                win_rate = (stats["wins"] / total) * 100
                body += (
                    f"  • {signal}: "
                    f"{stats['wins']}W / {stats['losses']}L "
                    f"({win_rate:.1f}% win rate, {total} trades)\n"
                )

    # Overall stats
    all_trades = memory.get("trades", [])
    if all_trades:
        total = len(all_trades)
        wins = sum(1 for t in all_trades if t.get("outcome") == "win")
        win_rate = (wins / total * 100) if total > 0 else 0
        total_pnl = sum(t.get("pnl", 0) for t in all_trades)

        body += f"\n\n📊 OVERALL STATS ({total} trades):\n\n"
        body += f"  Win Rate:  {win_rate:.1f}%\n"
        body += f"  Total P&L: ${total_pnl:,.2f}\n"

    body += "\n\n═══════════════════════════════════════════════════════════\n"
    body += "Automated report from your Day Trading Agent.\n"
    body += f"Strategy: VWAP Reclaim & ORB Breakout | 5-min bars | 1.5:1 R:R | Force close 3:50 PM ET\n"
    body += f"Generated: {datetime.now(tz=ET).strftime('%Y-%m-%d %H:%M ET')}\n"

    return body


# ---------------------------------------------------------------------------
# SMTP send
# ---------------------------------------------------------------------------

def send_email(to_email: str, subject: str, body: str) -> bool:
    if not all([config.EMAIL_FROM, config.SMTP_SERVER, config.SMTP_USER, config.SMTP_PASSWORD]):
        log.warning("Email credentials not fully configured in .env — skipping send")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = config.EMAIL_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)

        return True

    except Exception as e:
        log.error(f"Email send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    """Main email agent logic."""
    log.info("=" * 60)
    log.info("EMAIL AGENT STARTING")
    log.info("=" * 60)

    trade_log = load_trade_log()
    memory = load_strategy_memory()
    intraday_watchlist = load_intraday_watchlist()
    candidates = load_candidates()

    today = datetime.now(tz=ET).strftime("%Y-%m-%d")
    todays_closed = [t for t in trade_log["closed_trades"] if t.get("exit_date") == today]
    todays_pnl = sum(t.get("pnl", 0) for t in todays_closed)

    subject = (
        f"Day Trading Agent — {today} | "
        f"{len(todays_closed)} trades | "
        f"P&L: ${todays_pnl:+,.2f}"
    )

    body = format_email_body(trade_log, memory, intraday_watchlist, candidates)

    if not config.EMAIL_TO:
        log.warning("EMAIL_TO not set — printing summary instead")
        print("\n" + "=" * 60)
        print(body)
        print("=" * 60)
        return

    log.info(f"Sending daily summary to {config.EMAIL_TO}...")
    success = send_email(config.EMAIL_TO, subject, body)

    if success:
        log.info(f"Daily summary sent successfully to {config.EMAIL_TO}")
    else:
        log.warning("Email send failed — printing summary to log")
        log.info("\n" + body)

    log.info("EMAIL AGENT COMPLETE")


if __name__ == "__main__":
    run()
