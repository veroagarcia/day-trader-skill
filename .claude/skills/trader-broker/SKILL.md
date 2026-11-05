---
name: trader-broker
description: >-
  Simulated Order Executor. SIMULATION ONLY, USD 1,000 of pretend money, no
  broker, no real orders. Shows each proposed order as a plain ticket marked
  SIMULATED (a bracket shows its stop-loss, take-profit and the max loss at
  the stop), records the user's yes word for word, and only then records the
  simulated fill in trader/portfolio.json. Builds the sell ticket that closes a
  simulated day trade by the flat-by time, and logs each trade's max loss so
  trader-risk can hold the daily limit. Use when the user says "record the
  trade", "buy it" or "sell it" (in the simulation), "close my position",
  "flatten", or after /trader-risk passes. Refuses real money, brokers, live
  trading, options, margin and short selling.
argument-hint: "[order number]"
---

# trader-broker

This is the Order Executor of a **simulation**. The account is USD 1,000 of
pretend money. **No broker is connected, none may be connected, and no real
order can be placed.** Nothing here is sent anywhere: "placing" an order means
recording a simulated fill in `trader/portfolio.json`.

If the user asks to trade for real, use real money, go live, connect Alpaca,
Interactive Brokers or any other broker, or to paste API keys: **refuse**, say
this project is a USD 1,000 simulation, and do not offer a workaround. Do not
call any broker or trading tool, even if one appears in the session.

A simulated order is recorded only after two things, every time, for every order:

1. **trader-risk passed this exact order today** (matched by fingerprint).
2. **The user typed the exact confirmation for this one order** in the chat:
   `yes <order ID>`, where the order ID is the 16-character ID printed on that
   ticket. A bare "yes", "yes to all", "sure", a yes with a stock or an amount,
   or the ID of a different order is **not** a confirmation.

No confirmation, no record. The tool also refuses unless `trader/config.json` is a
simulation config (`"mode": "simulation"`, `"broker": "none"`, `"paper": true`,
`"sim_capital_usd": 1000`, margin, options and short selling all false) and
`trader/portfolio.json` can only change through `ticket.py result` after a yes.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                     # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes <order ID>"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --filled-qty 8 --filled-price 364.20
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol TSLA --qty 8
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker or to the network. It renders tickets,
checks that a reply is a real yes for that order, builds the flatten ticket,
updates the simulated portfolio and keeps the log in `trader/state/broker.json`.
`--now "2026-10-19 10:15"` pins the clock (New York time).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/config.json` | the simulation rules; the tool stops if it is not a simulation config |
| `trader/orders.json` | the proposed orders (trader-budget writes it; `flatten` replaces it) |
| `trader/state/risk.json` | trader-risk's verdicts; only a PASS from today is READY |
| `trader/state/broker.json` | every yes, no and simulated fill, with each entry's max loss |
| `trader/portfolio.json` | simulated cash and shares, changed only by `result` after a yes |
| `trader/plan.json` | the flat-by time for `flatten` |

These files live in the project. A cloud session's disk is erased when the
session ends, so tell the user that the history survives only if they commit
and push `trader/` (never do it without their say-so).

## Steps: the entry

1. `ticket.py show`. Only READY tickets go to the user. A ticket that is NOT
   READY or BLOCKED goes back to `/trader-risk`.
2. Show ONE ticket, with its order ID, and ask the user to reply exactly
   `yes <order ID>` to record it, or "no" to skip it. One order per question.
   Never offer "yes to all".
3. Run `ticket.py approve --index N --reply "<the user's reply, word for word>"`.
   If it prints "Not recorded", the reply was not the exact confirmation of
   this order (a bare yes, "yes to all", "sure", or another order's ID). Show
   the ticket again. Never type the order ID for the user and never turn a
   reply into a confirmation yourself.
4. Only after "Recorded your confirmation", take a market price for the fill (the last
   price from `trader/prices.json` or the entry bar; say where it came from) and run
   `ticket.py result --index N --status placed --filled-qty Q --filled-price P`.
   Or `--status denied` / `--status failed` with `--note`. A fill bigger than
   the approved order, a buy that costs more than the simulated cash, and a sell
   of more than is held are all refused (no margin, no short).

## Steps: while it is open, and out by the close

- trader-alerts watches the stop, the target and the flat-by time
  (`alerts.py add --from-plan`). In the simulation they are plan levels:
  nothing sells by itself.
- When the stop, the target or `flat_by` (15:55 New York) is reached, the exit
  is a new simulated order and needs its own yes:
  1. `ticket.py flatten --symbol TSLA --qty 8` writes a market sell for shares
     the simulated portfolio holds (never more) to `trader/orders.json`.
  2. `/trader-risk`. A sell that only closes what the user holds is never
     blocked by the daily limits or the entry window.
  3. `ticket.py show`, then the user's `yes <order ID>` for that one order, then
     `ticket.py approve` and `ticket.py result` with the fill price, as above.

## Example: the reel (original numbers, $5,000 account)

The numbers below come from the original pack's $5,000 example. In this
project the account is USD 1,000 and the code refuses a bigger budget, so a
real session sizes smaller (the config's `max_loss_per_trade_usd` is 10).

```
ORDER 1 of 1, SIMULATED (USD 1,000 of pretend money, no broker, nothing is sent anywhere)
  BUY 8 TSLA, market, good for today
  stop-loss 358.32
  take-profit 370.04
  max loss about $46.88 if the stop fills at 358.32 (it can fill worse in a fast market)
  READY: trader-risk PASS, waiting for your yes
  order ID: 0f3a9c1d7b2e4a65
  To record this one SIMULATED order reply exactly: yes 0f3a9c1d7b2e4a65
  (a bare yes, "yes to all" or another order's ID are not accepted). Reply "no" to skip it.
```

## What it never does

- Never connects to, calls or configures a broker, and never uses real money.
- Never records a simulated buy or sell without trader-risk's PASS and the user's `yes <order ID>` for that exact order.
- Never records two orders on one confirmation.
- Never asks for, reads, stores or repeats API keys or passwords.
- Never changes `mode`, `paper`, `broker`, `sim_capital_usd`, `allow_margin`,
  `allow_options` or `allow_short` in `trader/config.json`.
- Never places orders from a scheduled or background task: nobody is there to say yes.
- Never promises a fill price: a simulated fill is optimistic (no slippage, no queue).

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- SIMULATION ONLY: USD 1,000 of pretend money. No real orders, no broker, no real money.
- No simulated buy or sell is recorded without trader-risk's PASS on that exact order and the
  user's `yes <order ID>` for it in the chat.
- No options, margin, short selling or leverage: the code refuses them.
- No credentials or personal data in any file of this project.
