I want you to help me build a stock trading agent. 

We're going to be integrating with Alpaca to execute our buy and sell orders for our stocks, so I'm going to need your help with that. Let me know if you need API keys or API documentation in order to make that happen. We're only going to be using the paper trading account. We are not going to execute real trades here.

Here's what I want to build, feel free to analyze this and let me know whether this agentic workflow is sufficient or you want to build more / other agents. Do NOT start building before we agree on the design and plan.

1. A research agent that every morning will go scrape the internet for the latest stock news and financial market news, so that we understand what's going on in different industries and across the broader market, and how our trading strategy fits into the larger financial landscape.

1. A swing trader agent that executes our trading strategy. I want you to scrape the internet and look up the best, most profitable swing trading strategies, and 
implement your favorite one. If we need to increase our research interval from every morning to more frequent to execute a more fast-paced day trading strategy, that is okay — you let me know what works best.

1. Once our brain and strategy are set up, I want to be able to execute all those buys and sells inside our paper trading account in Alpaca.For pulling in live data — use Alpaca's API to get latest prices and intraday 
bars. For the trading logic, build a strategy Python file with clear rules for determining what to buy and sell, including what signals trigger a buy vs. hold vs. sell. Once the setup is ready, execute a couple of test trades so I can see them appear in my Alpaca dashboard.

I also want you to create a watch list of the stocks that you think are best for swing trading.  This watchlist should be updated as you learn. THe watch list should contain abut 25 stocks. This agent 
should run pre-market every morning, scan a large universe of stocks, score each one by volume, volatility, and news, and hand Claude a ranked short list of in-play stocks for that day. Both the research and trading agents should pull from that live list. Also set this up so it runs automatically in the background on my Mac without me having to manually start it in the terminal every day — create a start.sh and stop.sh and set up a Launch Agent so it starts on login and stays alive.

In the trading strategy also consider the stock momentun and basic technical patterns

I want this stock trading agent to be 
self-learning. As we perform this strategy and place trades — making money and losing money — I want all of that output, all of our trade results, P&L, signals, and Claude's reasoning, to be fed back into you and your brain so that we are always improving. I want you, my stock trading agent, to evolve as we go. Learn from the mistakes, learn from the wins, and feed all of that back into yourself as a persistent history — a living strategy memory file — so that you can train on it and improve our strategy going forward. 

Send me a summary email at the end of trading explaining all the trades that were executed and what you leant from these trades.

Also referesh the watch list every day