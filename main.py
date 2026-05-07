#!/usr/bin/env python3
"""
Main orchestrator: Chains all agents in sequence on schedule.
"""
import time
import schedule
from datetime import datetime
from agents import watchlist_agent, research_agent, strategy_agent, execution_agent, memory_agent, email_agent, universe_agent
import config
from logger import get_logger

log = get_logger("orchestrator")


def weekly_universe_refresh():
    log.info("=" * 60)
    log.info("WEEKLY UNIVERSE REFRESH STARTING")
    log.info("=" * 60)
    try:
        universe_agent.run()
        log.info("UNIVERSE REFRESH COMPLETE")
    except Exception as e:
        log.error(f"ERROR refreshing universe: {e}", exc_info=True)


def morning_sequence():
    log.info("=" * 60)
    log.info("MORNING SEQUENCE STARTING")
    log.info("=" * 60)
    try:
        log.info("Step 1/4: Watchlist Agent")
        watchlist_agent.run()
        time.sleep(5)

        log.info("Step 2/4: Research Agent")
        research_agent.run()
        time.sleep(5)

        log.info("Step 3/4: Strategy Agent")
        strategy_agent.run()
        time.sleep(5)

        log.info("Step 4/4: Execution Agent")
        execution_agent.run()

        log.info("MORNING SEQUENCE COMPLETE")
    except Exception as e:
        log.error(f"ERROR in morning sequence: {e}", exc_info=True)


def intraday_execution():
    log.info("--- Intraday execution check ---")
    try:
        execution_agent.run()
    except Exception as e:
        log.error(f"ERROR in intraday execution: {e}", exc_info=True)


def end_of_day_watchlist():
    log.info("--- End-of-day watchlist refresh ---")
    try:
        watchlist_agent.run()
    except Exception as e:
        log.error(f"ERROR refreshing watchlist: {e}", exc_info=True)


def end_of_day_email():
    log.info("--- Sending daily summary email ---")
    try:
        email_agent.run()
    except Exception as e:
        log.error(f"ERROR sending email: {e}", exc_info=True)


def end_of_day_memory():
    log.info("=" * 60)
    log.info("END-OF-DAY MEMORY UPDATE STARTING")
    log.info("=" * 60)
    try:
        memory_agent.run()
        log.info("MEMORY UPDATE COMPLETE")
    except Exception as e:
        log.error(f"ERROR in memory update: {e}", exc_info=True)


def setup_schedule():
    schedule.every().monday.at("06:30").do(weekly_universe_refresh)
    log.info("Scheduled: weekly universe refresh — Monday 06:30 ET")

    schedule_time = f"{config.WATCHLIST_HOUR:02d}:{config.WATCHLIST_MINUTE:02d}"
    schedule.every().day.at(schedule_time).do(morning_sequence)
    log.info(f"Scheduled: morning sequence — {schedule_time} ET")

    for hour in range(9, 16):
        for minute in [0, 30]:
            schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(intraday_execution)
    log.info("Scheduled: intraday execution checks — every 30 min 9am-4pm ET")

    email_time = f"{config.EMAIL_HOUR:02d}:{config.EMAIL_MINUTE:02d}"
    schedule.every().day.at(email_time).do(end_of_day_email)
    log.info(f"Scheduled: daily email — {email_time} ET")

    eod_watchlist_time = f"{config.WATCHLIST_EOD_HOUR:02d}:{config.WATCHLIST_EOD_MINUTE:02d}"
    schedule.every().day.at(eod_watchlist_time).do(end_of_day_watchlist)
    log.info(f"Scheduled: EOD watchlist refresh — {eod_watchlist_time} ET")

    eod_time = f"{config.MEMORY_HOUR:02d}:{config.MEMORY_MINUTE:02d}"
    schedule.every().day.at(eod_time).do(end_of_day_memory)
    log.info(f"Scheduled: EOD memory update — {eod_time} ET")


def main():
    log.info("=" * 60)
    log.info("STOCK TRADING AGENT STARTING")
    log.info("=" * 60)

    setup_schedule()

    log.info("Running startup morning sequence...")
    morning_sequence()

    log.info("Agent running. Waiting for scheduled jobs...")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Shutting down gracefully...")
