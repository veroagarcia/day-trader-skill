# The Day Trader skill

11 Claude skills for day trading: scan thousands of charts, track breaking news, time every entry and exit, and replay every outcome before you risk a dollar.

> **SIMULATION ONLY.** This copy is configured for practice with **USD 1,000 of pretend money**. No broker is
> connected, none can be connected, and no real order can be placed. The code refuses real-money settings,
> brokers, margin, options and short selling, and it records a simulated buy or sell only after you type
> `yes <order ID>` for that exact order.

Free, MIT, no signup, no API key. The tools are plain Python that read free
public data: Yahoo Finance charts, Nasdaq Trader's symbol lists, SEC EDGAR
and the House Clerk.

One scans thousands of charts for setups. Another tracks breaking news on
every stock you watch. One watches a setup bar by bar and tells you the moment
to get in, and another sets your stop and your target before you do. And the
craziest one is the Time Machine: before you risk a dollar, it replays the
rest of the session 10,000 times from the stock's own recent bars, plus every
past day the same setup fired, and tells you the honest odds.

Nothing in this project can place a real order. Every "trade" is a line in a
simulated portfolio, and none is recorded without your confirmation.

> This is a modified copy of the Day Trader skill by Jake Schincariol (MIT, see
> `LICENSE`). The original pack also described connecting a broker; that part
> was removed here on purpose. Do not install the upstream pack over this one.

## Setup

Nothing to install. The 11 skills are project-local, in `.claude/skills/`, and
Claude Code loads them when you open a session in this folder:

```
.claude/skills/trader-*/     the 11 skills (SKILL.md + one Python tool each)
.claude/settings.json        blocks broker connectors; asks before recording a simulated trade
trader/config.json           the simulation rules (USD 1,000, no margin, options or shorts)
trader/portfolio.json        the simulated account: USD 1,000 in cash, no positions
```

The tools need Python 3.8 or newer. Nothing to pip install. Do not add a broker
connector, API keys or real-money settings: the tools stop with a
"simulation guard" error if `trader/config.json` is not the simulation config.

The SEC tools (news filings, the analyst) ask you to identify yourself. That is
optional and not set here; without it they skip the SEC part. If you choose to
set `SEC_USER_AGENT` in your environment, it is sent to the SEC only.

## The eleven

Claude Code names project skills by folder, so they run as `/trader-scanner`
and so on.

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans thousands of charts for setups: opening-range breakouts, flags, oversold bounces. |
| `/trader-news` | News Monitor | Tracks breaking news on every stock you watch and flags what moves it. |
| `/trader-entry` | Entry Timer | Watches a setup bar by bar and tells you the moment to get in. |
| `/trader-exit` | Exit Planner | Sets your stop and your target before you enter, so you know when to get out. |
| `/trader-timemachine` | Time Machine | Replays every possible outcome of a trade before you risk a dollar: 10,000 simulated sessions plus every past time the setup fired. |
| `/trader-risk` | Risk Manager | Checks every trade against your limits and stops anything over them. |
| `/trader-budget` | Budget Manager | Sizes every position to your budget and your max loss per trade. |
| `/trader-broker` | Simulated Order Executor | Records simulated fills in the pretend portfolio, one order at a time, only after your `yes <order ID>`. No broker. |
| `/trader-alerts` | Price Alerts | Rings when a price, a stop or the opening bell hits. |
| `/trader-analyst` | Earnings Analyst | Reads earnings reports and sums up what changed. |
| `/trader-pelosi` | Pelosi Tracker | Reads Congress's stock-trade disclosures the minute they are filed. |

## How to use it

Everything lands in the `trader/` folder of this project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one simulated trade)
alerts: stop, target, flat by the close                                       (while it is open)
news / analyst / pelosi                                                        (on a schedule)
```

An example, the trade in the original reel: Tesla, Monday October 19 2026, real data.
The reel used a $5,000 account; in this project the account is USD 1,000, so the
same trade sizes smaller (see `trader/config.json`: max loss per trade is $10).

1. **`/trader-scanner`** at 10:15 AM ET: of the 231 charts in the reel's
   scan, 42 had closed above their 15-minute opening range. TSLA is one: range 354.47 to 362.18,
   the 10:10 candle closed at 364.18, 0.55 % over the top.
2. **`/trader-news`**: the morning's TSLA headlines, in New York time. Tesla
   reports this week: a day trade is out before the close, so it is not
   exposed to the report.
3. **`/trader-entry`** watched TSLA bar by bar. At 10:15 it said triggered: the
   first 5-minute close above the range, 364.18.
4. **`/trader-exit`** set the plan before the entry: stop at the range's
   midpoint, 358.32, so 5.86 a share at risk; target one times that risk,
   370.04; flat by 3:55 PM either way.
5. **`/trader-timemachine`** replayed the rest of the day 10,000 times from
   TSLA's own candles over the previous 59 sessions (seed 19, so anyone can
   repeat it): target first 29.4 %, stop first 25.5 %, still open at the close
   45.1 %. Its verdict: close to a coin flip. That is the point of looking
   before you risk a dollar.
6. **`/trader-budget`** with the USD 1,000 account and the $10 max loss: 1 share
   (5.86 at risk). It writes one simulated bracket order: buy 1 TSLA, stop-loss
   358.32, take-profit 370.04.
7. **`/trader-risk`** checks it against your limits: the max loss, the daily
   loss limit, trades per day, reward to risk, the entry window, position
   size and cash. PASS or BLOCK, with the reason.
8. **`/trader-broker`** shows you the ticket in plain words, marked SIMULATED,
   with its order ID. To record it you reply exactly `yes <that ID>`. A bare
   yes, "yes to all" or another order's ID is refused. Claude Code then asks
   once more before it runs the recording command.
9. **`/trader-alerts`** rings on the stop, the target and at 3:55 PM. A level
   being reached sells nothing by itself: the exit is a new simulated order
   with its own ticket and its own confirmation.

## The tools

All standard-library Python. The data tools read public endpoints and are
polite about it. Paths are from the project root.

```bash
python3 .claude/skills/trader-scanner/scan.py universe                  # ~5,900 US stocks, Nasdaq Trader
python3 .claude/skills/trader-scanner/scan.py daily                     # pre-market setups, whole universe
python3 .claude/skills/trader-scanner/scan.py orb --at 10:15            # opening-range breakouts so far
python3 .claude/skills/trader-news/news.py --tickers TSLA --hours 12    # headlines, 8-Ks, today's move
python3 .claude/skills/trader-entry/entry.py check TSLA --setup orb     # waiting / triggered / expired
python3 .claude/skills/trader-exit/exit.py plan --stop or-mid --target 1R --write
python3 .claude/skills/trader-timemachine/timemachine.py run --write    # 10,000 replays + the history
python3 .claude/skills/trader-budget/size.py --write                    # -> trader/orders.json
python3 .claude/skills/trader-risk/check.py                             # PASS / BLOCK per order
python3 .claude/skills/trader-broker/ticket.py show                     # the tickets, READY or not
python3 .claude/skills/trader-alerts/alerts.py add --from-plan          # stop, target, flat by close
python3 .claude/skills/trader-analyst/facts.py TSLA                     # quarters, growth, EPS
python3 .claude/skills/trader-pelosi/ptr.py index --member pelosi       # her PTRs this year
```

The tests run offline, on fixtures cut from real data, and reproduce the
reel's numbers plus the simulation guarantees (no real money, a confirmation
for every simulated trade):

```bash
python3 -m unittest discover -s tests -v
```

## Fine print

**Not financial advice.** This is software that reads public data and does
arithmetic. It does not know your situation and it cannot see the future.
Most people who day trade lose money. Decide for yourself, and talk to a
licensed professional if you need advice.

**Simulation only, no real orders.** Only `/trader-broker` changes the
simulated portfolio, and only after `/trader-risk` passes that exact order and
you reply `yes <order ID>` in the chat. There is no broker connection, no API
key and no real money anywhere in this project. If you want to trade for real
one day, that is a separate decision outside this project.

**Simulated results are optimistic.** A simulated fill has no slippage, no
queue and no rejected orders, and the price you record comes from free,
delayed data. Real trading would do worse.

**The Time Machine is a simulation, not a prediction.** It is built from the
stock's own last 60 days of 5-minute bars. The future can do things those 60
days never did: an earnings report, a halt, a headline. Treat its odds as a
reality check, never as a promise.

**A stop is a plan, not a guarantee.** In a fast market or across a gap, a
stop can fill well past its price. In this simulation a stop is a plan level:
nothing sells by itself.

**The data is free and unofficial.** Yahoo Finance's chart endpoint is not an
official API: it can lag, change or rate-limit you. The scanner and the entry
timer read 1-minute or 5-minute bars, not every tick. Check anything that
matters against an official source.

**Day-trading rules.** FINRA removed the $25,000 pattern-day-trader minimum
on June 4, 2026 (Regulatory Notice 26-10), and brokers may phase the change
in until October 20, 2027. Set `"pdt_guard": true` in `trader/config.json` if
you want `/trader-risk` to count your day trades anyway.

**Congress's trades are public, not inside information.** Members must disclose
trades over $1,000 within 45 days (the STOCK Act). The Pelosi skill reads those
public filings the minute they post.

**Taxes.** Nothing here is tax advice.

## Files

```
.claude/skills/
  trader-scanner/     SKILL.md, scan.py
  trader-news/        SKILL.md, news.py
  trader-entry/       SKILL.md, entry.py
  trader-exit/        SKILL.md, exit.py
  trader-timemachine/ SKILL.md, timemachine.py
  trader-risk/        SKILL.md, check.py
  trader-budget/      SKILL.md, size.py, config.example.json, targets.example.json
  trader-broker/      SKILL.md, ticket.py
  trader-alerts/      SKILL.md, alerts.py, alerts.example.json
  trader-analyst/     SKILL.md, facts.py, metrics.example.json
  trader-pelosi/      SKILL.md, ptr.py
.claude/settings.json  broker connectors denied; asks before recording a simulated trade
.claude-plugin/        plugin metadata for this simulation-only copy
trader/                simulation config, portfolio and logs (commit them to keep the history)
tests/                 unittest suite + offline fixtures
```

MIT. Original pack by [Jake Schincariol](https://opusjake.ai); simulation-only
changes in this copy.
