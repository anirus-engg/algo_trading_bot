#!/usr/bin/env python3
"""
Main orchestrator: Chains all agents in sequence.
Runs on schedule via cron or Launch Agent.
"""
import time
import schedule
from datetime import datetime
from agents import watchlist_agent, research_agent, strategy_agent, execution_agent, memory_agent, email_agent
import config


def morning_sequence():
    """Run the full morning agent sequence."""
    print(f"\n{'='*60}")
    print(f"[{datetime.now()}] Starting morning sequence")
    print(f"{'='*60}\n")
    
    try:
        # 1. Watchlist
        watchlist_agent.run()
        time.sleep(5)
        
        # 2. Research
        research_agent.run()
        time.sleep(5)
        
        # 3. Strategy
        strategy_agent.run()
        time.sleep(5)
        
        # 4. Execution
        execution_agent.run()
        
        print(f"\n[{datetime.now()}] Morning sequence complete\n")
    
    except Exception as e:
        print(f"\n[{datetime.now()}] ERROR in morning sequence: {e}\n")


def intraday_execution():
    """Run execution agent for position management."""
    print(f"\n[{datetime.now()}] Running intraday execution check...")
    try:
        execution_agent.run()
    except Exception as e:
        print(f"[{datetime.now()}] ERROR in intraday execution: {e}")


def end_of_day_watchlist():
    """Refresh watchlist at end of day so it's ready for tomorrow morning."""
    print(f"\n[{datetime.now()}] Refreshing end-of-day watchlist...")
    try:
        watchlist_agent.run()
        print(f"[{datetime.now()}] Watchlist refreshed\n")
    except Exception as e:
        print(f"\n[{datetime.now()}] ERROR refreshing watchlist: {e}\n")


def end_of_day_email():
    """Send daily summary email."""
    print(f"\n{'='*60}")
    print(f"[{datetime.now()}] Sending daily summary email")
    print(f"{'='*60}\n")
    
    try:
        email_agent.run()
        print(f"\n[{datetime.now()}] Email sent\n")
    except Exception as e:
        print(f"\n[{datetime.now()}] ERROR sending email: {e}\n")


def end_of_day_memory():
    """Run memory agent after market close."""
    print(f"\n{'='*60}")
    print(f"[{datetime.now()}] Running end-of-day memory update")
    print(f"{'='*60}\n")
    
    try:
        memory_agent.run()
        print(f"\n[{datetime.now()}] Memory update complete\n")
    except Exception as e:
        print(f"\n[{datetime.now()}] ERROR in memory update: {e}\n")


def setup_schedule():
    """Set up the daily schedule."""
    # Morning sequence
    schedule_time = f"{config.WATCHLIST_HOUR:02d}:{config.WATCHLIST_MINUTE:02d}"
    schedule.every().day.at(schedule_time).do(morning_sequence)
    print(f"Scheduled morning sequence at {schedule_time} ET")
    
    # Intraday execution checks (every 30 min from 9am to 4pm)
    for hour in range(9, 16):
        for minute in [0, 30]:
            schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(intraday_execution)
    print(f"Scheduled intraday execution checks every 30 min (9am-4pm ET)")
    
    # End of day: email → watchlist refresh → memory (in sequence, 15 min apart)
    email_time = f"{config.EMAIL_HOUR:02d}:{config.EMAIL_MINUTE:02d}"
    schedule.every().day.at(email_time).do(end_of_day_email)
    print(f"Scheduled daily summary email at {email_time} ET")

    eod_watchlist_time = f"{config.WATCHLIST_EOD_HOUR:02d}:{config.WATCHLIST_EOD_MINUTE:02d}"
    schedule.every().day.at(eod_watchlist_time).do(end_of_day_watchlist)
    print(f"Scheduled end-of-day watchlist refresh at {eod_watchlist_time} ET")

    eod_time = f"{config.MEMORY_HOUR:02d}:{config.MEMORY_MINUTE:02d}"
    schedule.every().day.at(eod_time).do(end_of_day_memory)
    print(f"Scheduled end-of-day memory update at {eod_time} ET")


def main():
    """Main loop."""
    print(f"\n{'='*60}")
    print(f"Stock Trading Agent - Starting")
    print(f"{'='*60}\n")
    
    setup_schedule()
    
    print(f"\nAgent is running. Press Ctrl+C to stop.\n")
    
    # Run immediately on startup for testing
    print("[STARTUP] Running morning sequence immediately for testing...")
    morning_sequence()
    
    # Then run on schedule
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nShutting down gracefully...\n")
