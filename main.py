#!/usr/bin/env python3
"""
Main orchestrator: Day trading agent scheduler.

Daily schedule (ET):
  06:30 Mon  — Universe refresh (weekly)
  08:00      — Daily watchlist scan (Stage 1)
  08:30      — Research / news sentiment
  09:15      — Gap filter (Stage 2a) — quote vs prior close
  09:35      — Volume confirm (Stage 2b) — first 5-min bar
  09:45–3:50 — Strategy + execution every 5 min (VWAP reclaim scoring)
  15:50      — Force close (handled inside execution agent)
  16:15      — Daily summary email
  16:30      — EOD memory update + watchlist refresh
"""
import time
import schedule
from datetime import datetime, date
from zoneinfo import ZoneInfo
from agents import (
    watchlist_agent, research_agent, strategy_agent,
    execution_agent, memory_agent, email_agent, universe_agent,
)
import config
from logger import get_logger

log = get_logger("orchestrator")

ET = ZoneInfo("America/New_York")

# US market holidays 2025-2026 (NYSE observed dates)
MARKET_HOLIDAYS = {
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # MLK Day
    date(2025, 2, 17),  # Presidents' Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving
    date(2025, 12, 25), # Christmas
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
    # TODO: add 2027 NYSE holidays before end of 2026
}


def is_market_day(dt: datetime = None) -> bool:
    """Returns True if today is a trading day (Mon–Fri, not a holiday)."""
    if dt is None:
        dt = datetime.now(tz=ET)
    today = dt.date()
    if today.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    if today in MARKET_HOLIDAYS:
        return False
    return True


def skip_if_not_market_day(fn):
    """Decorator — skips the job and logs a message if today is not a trading day."""
    def wrapper(*args, **kwargs):
        if not is_market_day():
            now = datetime.now(tz=ET)
            day_name = now.strftime("%A")
            log.debug(f"Skipping {fn.__name__} — not a market day ({day_name})")
            return
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

def weekly_universe_refresh():
    log.info("=" * 60)
    log.info("WEEKLY UNIVERSE REFRESH")
    log.info("=" * 60)
    try:
        universe_agent.run()
    except Exception as e:
        log.error(f"Universe refresh failed: {e}", exc_info=True)


@skip_if_not_market_day
def morning_watchlist():
    """Stage 1: Score universe → top 25 watchlist."""
    log.info("--- Morning watchlist scan (Stage 1) ---")
    try:
        watchlist_agent.run()
    except Exception as e:
        log.error(f"Watchlist scan failed: {e}", exc_info=True)


@skip_if_not_market_day
def morning_research():
    """News sentiment for the watchlist."""
    log.info("--- Morning research / news sentiment ---")
    try:
        research_agent.run()
    except Exception as e:
        log.error(f"Research agent failed: {e}", exc_info=True)


@skip_if_not_market_day
def intraday_cycle():
    """
    Core intraday loop — runs every 5 minutes from 9:45 AM to 3:50 PM ET.
    1. Strategy agent: score VWAP reclaim setups on latest 5-min bars
    2. Execution agent: enter new positions, check exits, force close at 3:50 PM
    """
    now_et = datetime.now(tz=ET)
    hour, minute = now_et.hour, now_et.minute

    # Only run during market hours (9:30 AM – 4:00 PM ET)
    if not (9 <= hour < 16):
        return

    # Skip the opening range formation window (9:30–9:44 AM) for new entries
    # but still run execution agent to check exits on any existing positions
    if hour == 9 and minute < 45:
        log.debug(f"Opening range window ({hour}:{minute:02d} ET) — execution check only")
        try:
            execution_agent.run()
        except Exception as e:
            log.error(f"Execution agent failed: {e}", exc_info=True)
        return

    try:
        strategy_agent.run()
    except Exception as e:
        log.error(f"Strategy agent failed: {e}", exc_info=True)

    try:
        execution_agent.run()
    except Exception as e:
        log.error(f"Execution agent failed: {e}", exc_info=True)


@skip_if_not_market_day
def end_of_day_email():
    log.info("--- Sending daily summary email ---")
    try:
        email_agent.run()
    except Exception as e:
        log.error(f"Email agent failed: {e}", exc_info=True)


@skip_if_not_market_day
def end_of_day_memory():
    log.info("--- EOD memory update ---")
    try:
        memory_agent.run()
    except Exception as e:
        log.error(f"Memory agent failed: {e}", exc_info=True)


@skip_if_not_market_day
def end_of_day_watchlist():
    log.info("--- EOD watchlist refresh ---")
    try:
        watchlist_agent.run()
    except Exception as e:
        log.error(f"EOD watchlist refresh failed: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Schedule setup
# ---------------------------------------------------------------------------

def setup_schedule():
    # Weekly universe refresh — Monday pre-market
    schedule.every().monday.at(
        f"{config.UNIVERSE_HOUR:02d}:{config.UNIVERSE_MINUTE:02d}"
    ).do(weekly_universe_refresh)
    log.info(f"Scheduled: universe refresh — Monday {config.UNIVERSE_HOUR:02d}:{config.UNIVERSE_MINUTE:02d} ET")

    # Daily watchlist scan — 8:00 AM
    schedule.every().day.at(
        f"{config.WATCHLIST_HOUR:02d}:{config.WATCHLIST_MINUTE:02d}"
    ).do(morning_watchlist)
    log.info(f"Scheduled: watchlist scan — {config.WATCHLIST_HOUR:02d}:{config.WATCHLIST_MINUTE:02d} ET")

    # Research / news — 8:30 AM
    schedule.every().day.at(
        f"{config.RESEARCH_HOUR:02d}:{config.RESEARCH_MINUTE:02d}"
    ).do(morning_research)
    log.info(f"Scheduled: research — {config.RESEARCH_HOUR:02d}:{config.RESEARCH_MINUTE:02d} ET")

    # Intraday cycle — every 5 minutes from 9:30 AM to 4:00 PM
    # schedule library doesn't support "every N minutes between X and Y" natively,
    # so we schedule every 5 minutes all day and gate inside intraday_cycle()
    schedule.every(config.EXECUTION_INTERVAL_MINUTES).minutes.do(intraday_cycle)
    log.info(
        f"Scheduled: intraday cycle — every {config.EXECUTION_INTERVAL_MINUTES} min "
        f"(active {config.TRADING_START_HOUR}:{config.TRADING_START_MINUTE:02d}–"
        f"{config.FORCE_CLOSE_HOUR}:{config.FORCE_CLOSE_MINUTE:02d} ET)"
    )

    # EOD email — 4:15 PM
    schedule.every().day.at(
        f"{config.EMAIL_HOUR:02d}:{config.EMAIL_MINUTE:02d}"
    ).do(end_of_day_email)
    log.info(f"Scheduled: EOD email — {config.EMAIL_HOUR:02d}:{config.EMAIL_MINUTE:02d} ET")

    # EOD watchlist refresh — 4:30 PM
    schedule.every().day.at(
        f"{config.WATCHLIST_EOD_HOUR:02d}:{config.WATCHLIST_EOD_MINUTE:02d}"
    ).do(end_of_day_watchlist)
    log.info(f"Scheduled: EOD watchlist — {config.WATCHLIST_EOD_HOUR:02d}:{config.WATCHLIST_EOD_MINUTE:02d} ET")

    # EOD memory update — 4:30 PM
    schedule.every().day.at(
        f"{config.MEMORY_HOUR:02d}:{config.MEMORY_MINUTE:02d}"
    ).do(end_of_day_memory)
    log.info(f"Scheduled: EOD memory — {config.MEMORY_HOUR:02d}:{config.MEMORY_MINUTE:02d} ET")


# ---------------------------------------------------------------------------
# Startup sequence
# ---------------------------------------------------------------------------

def startup_sequence():
    """
    Run the appropriate startup steps based on current time.
    Skips entirely on weekends and holidays.
    """
    now_et = datetime.now(tz=ET)

    if not is_market_day(now_et):
        day_name = now_et.strftime("%A")
        log.info(f"Startup on {day_name} — not a market day, skipping startup sequence")
        log.info("Agent is running and will activate on the next trading day")
        return

    hour, minute = now_et.hour, now_et.minute
    log.info(f"Startup at {now_et.strftime('%H:%M ET')} — running appropriate steps...")

    if hour < 8:
        log.info("Pre-market: running watchlist scan")
        morning_watchlist()
    elif hour == 8 and minute < 30:
        log.info("8:00–8:30 AM: running watchlist + research")
        morning_watchlist()
        morning_research()
    elif hour == 8 or (hour == 9 and minute < 30):
        log.info("8:30–9:30 AM: running research")
        morning_research()
    elif 9 <= hour < 16:
        log.info("Market hours: running intraday cycle immediately")
        intraday_cycle()
    else:
        log.info("After market: no startup action needed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    log.info("=" * 60)
    log.info("DAY TRADING AGENT STARTING")
    log.info("Strategy: VWAP Reclaim | 5-min bars | 1.5:1 R:R | Force close 3:50 PM ET")
    log.info("Market days only (Mon–Fri, excl. holidays) — idle on weekends")
    log.info("=" * 60)

    setup_schedule()
    startup_sequence()

    log.info("Agent running. Waiting for scheduled jobs...")
    while True:
        schedule.run_pending()
        time.sleep(30)  # check every 30s — fine-grained enough for 5-min schedule


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Shutting down gracefully...")
