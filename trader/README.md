# trader/ : simulation records (USD 1,000 of pretend money)

Everything here is SIMULATED. No broker is connected and no real order can be placed.

- `config.json`     the rules. The tools refuse to run unless it is a simulation config.
- `portfolio.json`  the simulated account (cash and shares). Changed only by `ticket.py result`, after your yes.
- `state/broker.json`  append-only log of every yes, no and simulated fill.
- `orders.json`, `plan.json`, `state/risk.json`  working files for the trade in progress.

These files are part of the project on purpose: commit them to keep the simulation history.
A cloud session's disk is erased when the session ends; only what is committed and pushed survives.
No credentials or personal data belong in this folder.
