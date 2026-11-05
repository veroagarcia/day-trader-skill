#!/usr/bin/env python3
"""Simulated order tickets and the decision log for trader-broker. Standard library only.

SIMULATION ONLY. This project trades USD 1,000 of pretend money. No broker is
connected, none is ever called, and nothing here can place a real order. The
tool refuses to run unless trader/config.json is a simulation config (see the
simulation guard below). It does its work around the one moment that matters,
your yes:

  show      renders each proposed order as a plain-English ticket marked
            SIMULATED. An order is READY only if trader-risk passed THIS exact
            order today (matched by fingerprint) and nobody has decided on it.
  approve   records your explicit confirmation of ONE order, with your reply
            word for word. The reply must be exactly "yes <order ID>" with the
            ID printed on that ticket. A bare yes, "yes to all", the ID of
            another order and any other wording are refused, and so is any
            order that is not READY.
  decline   records a no.
  result    records the SIMULATED fill of an order you approved (price and
            quantity from market data) in trader/portfolio.json. It only works
            after your yes for that order. There is no other way to change the
            simulated portfolio.
  flatten   builds a sell ticket that closes a symbol's simulated position by
            flat_by. It still goes through trader-risk and your yes.
  log       prints today's decisions.

    python3 ticket.py show                    # every order, READY or not
    python3 ticket.py show --index 1 --json   # one ticket as JSON
    python3 ticket.py approve --index 1 --reply "yes <order ID>"
    python3 ticket.py result --index 1 --status placed --filled-qty 8 --filled-price 364.20
    python3 ticket.py flatten --symbol TSLA --qty 8
    python3 ticket.py log

Everything is written to trader/state/broker.json (append only). Dates are
New York dates; --now "2026-10-19 10:15" pins the clock.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

ALPACA_FIELDS = ("symbol", "side", "qty", "notional", "type", "time_in_force", "limit_price",
                 "stop_price", "trail_price", "trail_percent", "extended_hours", "client_order_id",
                 "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                 "stop_loss_limit_price", "advanced_instructions")
STRING_FIELDS = ("qty", "notional", "limit_price", "stop_price", "trail_price", "trail_percent",
                 "take_profit_limit_price", "stop_loss_stop_price", "stop_loss_limit_price")
TIF_WORDS = {"day": "good for today", "gtc": "good until canceled", "opg": "at the open",
             "cls": "at the close", "ioc": "immediate or cancel", "fok": "fill or kill"}
YES_WORDS = ("yes", "y")
BATCH_WORDS = {"all", "every", "everything", "rest", "remaining", "them", "both", "batch", "each"}
DOUBT_WORDS = {"no", "not", "dont", "don't", "wait", "cancel", "stop", "but", "maybe", "later",
               "hold", "unless", "if"}


# ==== BEGIN simulation guard (identical in trader-budget/size.py, trader-risk/check.py, trader-broker/ticket.py) ====
# This project is a paper simulation with USD 1,000 of pretend money. These checks do not trust the
# "paper" flag alone: the config must say so in several independent ways, or the tool refuses to run.
SIM_CAPITAL_USD = 1000.0
_SIM_SECRET_WORDS = ("key", "secret", "token", "password", "passwd", "credential")


def sim_config_violations(cfg):
    """Why this config is NOT a USD 1,000 simulation. An empty list means it is. Fails closed."""
    if not isinstance(cfg, dict) or not cfg:
        return ["trader/config.json is missing or empty: a simulation config is required"]
    v = []
    if cfg.get("mode") != "simulation":
        v.append('"mode" must be "simulation"')
    if cfg.get("paper") is not True:
        v.append('"paper" must be true')
    if cfg.get("broker") != "none":
        v.append('"broker" must be "none": no broker is ever connected')
    for k in ("allow_margin", "allow_options", "allow_short"):
        if cfg.get(k) is not False:
            v.append('"%s" must be false' % k)
    try:
        cap = float(cfg.get("sim_capital_usd"))
    except (TypeError, ValueError):
        cap = None
    if cap != SIM_CAPITAL_USD:
        v.append('"sim_capital_usd" must be 1000')
    try:
        budget = float(cfg.get("budget"))
    except (TypeError, ValueError):
        budget = None
    if budget is None or not 0 < budget <= SIM_CAPITAL_USD:
        v.append('"budget" must be above 0 and at most 1000')
    for k in cfg:
        if any(w in str(k).lower() for w in _SIM_SECRET_WORDS):
            v.append('"%s" looks like a credential: none belong in this project' % k)
    return v


def _sim_ticker_ok(sym):
    """A plain US stock ticker (AAPL, BRK.B). Option symbols, crypto pairs and anything odd fail."""
    s = str(sym or "").strip().upper()
    for sep in (".", "-"):
        if sep in s:
            s, suffix = s.split(sep, 1)
            if not (suffix.isalpha() and suffix.isascii() and 1 <= len(suffix) <= 2):
                return False
            break
    return s.isalpha() and s.isascii() and 1 <= len(s) <= 5


def sim_order_violations(order, doc=None):
    """Why this order cannot be part of the simulation (real-money flags, options, crypto, odd order classes)."""
    v = []
    if isinstance(doc, dict) and doc.get("paper") is False:
        v.append("the orders file says paper is false")
    if not isinstance(order, dict):
        return v + ["the order is not an object"]
    if not _sim_ticker_ok(order.get("symbol")):
        v.append("%r is not a plain US stock ticker (no options, crypto or other assets)" % (order.get("symbol"),))
    if str(order.get("side", "")).lower() not in ("buy", "sell"):
        v.append("side must be buy or sell")
    if str(order.get("order_class") or "simple").lower() not in ("simple", "bracket"):
        v.append("order_class %r is not allowed (only simple and bracket)" % (order.get("order_class"),))
    return v
# ==== END simulation guard ====


class TicketError(Exception):
    pass


# ---------------------------------------------------------------- time (New York, no tz files)

def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def eastern_offset(utc):
    """Hours from UTC for New York: -4 in daylight time, -5 otherwise.
    DST runs from 2:00 a.m. on the second Sunday of March to 2:00 a.m. on the
    first Sunday of November (US rule since 2007)."""
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))   # 2:00 EST
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))    # 2:00 EDT
    naive = utc.replace(tzinfo=None)
    return -4 if start <= naive < end else -5


def to_eastern(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=eastern_offset(utc))


def eastern_to_utc(local):
    for off in (-4, -5):
        utc = local - datetime.timedelta(hours=off)
        if eastern_offset(utc) == off:
            return utc
    return local + datetime.timedelta(hours=5)


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as New York time."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise TicketError("--now wants a time like \"2026-10-19 10:15\" (New York) or ...Z (UTC)")
    if dt.tzinfo is None:
        return eastern_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def ny_iso(now_utc):
    """naive UTC -> "2026-10-19T10:15:00-04:00" (New York wall clock with its offset)."""
    off = eastern_offset(now_utc)
    return "%s%+03d:00" % (to_eastern(now_utc).replace(microsecond=0).isoformat(), off)


# ---------------------------------------------------------------- files

def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise TicketError("no %s at %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise TicketError("%s is not valid JSON: %s" % (path, e))


def write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def rec_day(rec):
    """The trading day a decision belongs to: its "date" (the day it was made under), else the day of "at"."""
    return str(rec.get("date") or str(rec.get("at", ""))[:10])


# ---------------------------------------------------------------- the order

def fingerprint(order):
    """Same function as trader-risk/check.py: identifies the exact order."""
    core = {k: order[k] for k in ALPACA_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _str_num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f == int(f) else repr(f)
    return str(v)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def tool_input(order):
    """The order's fields (numbers as strings), without our own "why" and "plan". Shown to you, sent nowhere."""
    out = {}
    for k in ALPACA_FIELDS:
        if k in order and order[k] is not None:
            out[k] = _str_num(order[k]) if k in STRING_FIELDS else order[k]
    return out


def _money(v):
    f = float(v)
    s = "{:,.2f}".format(f)
    return "$" + (s[:-3] if s.endswith(".00") else s)


def _p(v):
    return "%.2f" % float(v)


def is_bracket(order):
    oc = str(order.get("order_class") or "").lower()
    legs = order.get("take_profit_limit_price") is not None or order.get("stop_loss_stop_price") is not None
    return oc == "bracket" or (not oc and legs)


def max_loss(order):
    """(dollars, stop) lost if the stop fills exactly at the stop, or (None, stop)."""
    stop = _f(order.get("stop_loss_stop_price")) or _f((order.get("plan") or {}).get("stop"))
    q = _f(order.get("qty"))
    if not stop or not q:
        return None, stop
    plan = order.get("plan") or {}
    if str(order.get("type", "market")) == "limit" and _f(order.get("limit_price")):
        entry = _f(order["limit_price"])
    elif _f(plan.get("max_loss")) is not None:
        return round(_f(plan["max_loss"]), 2), stop
    else:
        entry = _f(plan.get("entry"))
    if not entry:
        return None, stop
    risk = abs(entry - stop)
    return round(q * int(round(risk * 100)) / 100.0, 2), stop


def plain_parts(order):
    """The ticket in plain words, one part per line."""
    side = str(order.get("side", "")).upper()
    sym = order.get("symbol", "?")
    typ = str(order.get("type", "market"))
    tif = TIF_WORDS.get(str(order.get("time_in_force", "day")), order.get("time_in_force"))
    if is_bracket(order):
        how = "limit %s" % _p(order["limit_price"]) if typ == "limit" and order.get("limit_price") else typ
        parts = ["%s %s %s, %s, %s" % (side, _str_num(order.get("qty")), sym, how, tif)]
        if order.get("stop_loss_stop_price") is not None:
            leg = "stop-loss %s" % _p(order["stop_loss_stop_price"])
            if order.get("stop_loss_limit_price") is not None:
                leg += " (limit %s)" % _p(order["stop_loss_limit_price"])
            parts.append(leg)
        if order.get("take_profit_limit_price") is not None:
            parts.append("take-profit %s" % _p(order["take_profit_limit_price"]))
        loss, stop = max_loss(order)
        if loss is not None:
            parts.append("max loss about %s if the stop fills at %s (it can fill worse in a fast market)"
                         % (_money(loss), _p(stop)))
        return parts
    if order.get("notional") is not None:
        what = "%s of %s" % (_money(order["notional"]), sym)
    else:
        q = _str_num(order.get("qty"))
        what = "%s share%s of %s" % (q, "" if q == "1" else "s", sym)
    if typ == "limit":
        how = "limit order at %s" % _money(order.get("limit_price"))
    elif typ == "stop":
        how = "stop order at %s" % _money(order.get("stop_price"))
    elif typ == "stop_limit":
        how = "stop %s, limit %s" % (_money(order.get("stop_price")), _money(order.get("limit_price")))
    else:
        how = "%s order" % typ.replace("_", " ")
    return ["%s %s, %s, %s" % (side, what, how, tif)]


def plain(order):
    """BUY $1,250 of AAPL, market order, good for today
    BUY 8 TSLA, market, good for today / stop-loss 358.32 / take-profit 370.04 / max loss about $46.88 ..."""
    return " / ".join(plain_parts(order))


def amount_numbers(order):
    nums = []
    for k in ("notional", "qty", "limit_price", "stop_loss_stop_price", "take_profit_limit_price",
              "stop_loss_limit_price"):
        if order.get(k) is not None:
            v = _f(order[k])
            if v is not None:
                nums.append(v)
    loss, _ = max_loss(order)
    if loss is not None:
        nums.append(loss)
    return nums


CONFIRM = re.compile(r"^\s*(?:yes|confirm)[\s,:]+(?:order\s+(?:id\s+)?)?#?([0-9a-f]{16})\s*[.!]?\s*$", re.I)


def confirmation_text(order):
    """The one reply that confirms this order: "yes" plus its exact order ID (the fingerprint)."""
    return "yes " + fingerprint(order)


def parse_yes(reply, order, batch=()):
    """Is this reply the explicit confirmation of THIS exact order? Returns (ok, why).

    Only "yes <order ID>" counts, where the ID is this order's fingerprint. A bare yes, "yes to all",
    a yes with a stock or an amount, an ID of another order, or any other wording is refused."""
    raw = (reply or "").strip()
    if not raw:
        return False, "the reply is empty"
    want = fingerprint(order)
    m = CONFIRM.match(raw)
    if not m:
        return False, ("a confirmation must be exactly \"%s\" (yes plus this order's ID); a bare yes, "
                       "\"yes to all\", or any other wording is not accepted" % confirmation_text(order))
    got = m.group(1).lower()
    if got != want:
        others = {fingerprint(o) for o in batch if isinstance(o, dict)} - {want}
        if got in others:
            return False, "that ID belongs to a different order; this order's ID is %s" % want
        return False, "%s is not this order's ID; this order's ID is %s" % (got, want)
    return True, "confirmed order ID %s: %s" % (want, plain(order))


# ---------------------------------------------------------------- state

def load_state(path):
    return read_json(path, "broker state", required=False) or {"orders": []}


def latest(state, fp, today):
    """The latest decision recorded today for this fingerprint, or None."""
    found = None
    for rec in state.get("orders", []):
        if rec.get("fingerprint") == fp and rec_day(rec) == today:
            found = rec
    return found


def risk_verdict(risk, fp, today):
    if not risk:
        return None, "trader-risk has not checked these orders (run check.py)"
    if risk.get("date") != today:
        return None, "the risk check is from %s, not today; run check.py again" % risk.get("date")
    for r in risk.get("results", []):
        if r.get("fingerprint") == fp:
            return r, None
    return None, "this exact order was not in the last risk check (it changed or is new); run check.py again"


def status_of(order, risk, state, today):
    """(ready, label, risk_result)"""
    fp = fingerprint(order)
    rv, why = risk_verdict(risk, fp, today)
    if rv is None:
        return False, "NOT READY: " + why, None
    if rv.get("verdict") != "PASS":
        return False, "BLOCKED by trader-risk: " + "; ".join(rv.get("reasons", [])), rv
    rec = latest(state, fp, today)
    if rec:
        st = rec.get("status")
        if st == "approved":
            return False, "APPROVED by you at %s, waiting for the simulated fill (ticket.py result)" % rec.get("at"), rv
        return False, "DONE: %s at %s" % (st, rec.get("at")), rv
    return True, "READY: trader-risk PASS, waiting for your yes", rv


def kind_of(order, rv):
    """entry or exit, as trader-risk saw it (older checks: a buy is an entry)."""
    if rv and rv.get("kind"):
        return rv["kind"]
    return "entry" if str(order.get("side", "")).lower() == "buy" else "exit"


# ---------------------------------------------------------------- rendering

def render(order, idx, total, cfg, risk, state, today):
    ready, label, rv = status_of(order, risk, state, today)
    lines = ["ORDER %d of %d, SIMULATED (USD 1,000 of pretend money, no broker, nothing is sent anywhere)"
             % (idx, total)]
    for part in plain_parts(order):
        lines.append("  " + part)
    if order.get("why"):
        lines.append("  why: " + order["why"])
    lines.append("  " + label)
    for w in (rv or {}).get("warnings", []):
        lines.append("  note: " + w)
    if is_bracket(order):
        lines.append("  Simulated bracket: the stop-loss and the take-profit are plan levels, not live orders.")
        lines.append("  Each simulated sell still needs its own ticket and your yes.")
    if ready:
        lines.append("  order ID: " + fingerprint(order))
        lines.append("  To record this one SIMULATED order reply exactly: " + confirmation_text(order))
        lines.append("  (a bare yes, \"yes to all\" or another order's ID are not accepted). Reply \"no\" to skip it.")
    return "\n".join(lines), ready


def ticket_json(order, idx, cfg, risk, state, today):
    ready, label, rv = status_of(order, risk, state, today)
    loss, stop = max_loss(order)
    return {"index": idx, "ready": ready, "status": label, "plain": plain(order),
            "fingerprint": fingerprint(order), "order_id": fingerprint(order),
            "confirm_with": confirmation_text(order), "simulated": True, "broker": "none",
            "order": tool_input(order), "why": order.get("why", ""),
            "bracket": is_bracket(order), "max_loss": loss, "stop": stop}


# ---------------------------------------------------------------- fills -> portfolio

def apply_fill(portfolio_path, cfg, symbol, side, qty, price, date, approval=None):
    """Record a SIMULATED fill in trader/portfolio.json: cash and shares, with a
    cost-basis lot per buy (oldest lots are relieved first on a sell).

    The single door to the simulated portfolio: it needs a simulation config AND
    the recorded yes (approval) for this order. No margin: a buy cannot cost
    more than the cash. No short: a sell cannot exceed the shares held."""
    bad = sim_config_violations(cfg)
    if bad:
        raise TicketError("not a simulation config, refusing to touch the portfolio: " + "; ".join(bad))
    oid = str((approval or {}).get("confirmed_id") or "").lower() if isinstance(approval, dict) else ""
    if (not isinstance(approval, dict) or approval.get("status") != "approved" or not approval.get("reply")
            or not re.match(r"^[0-9a-f]{16}$", oid) or oid != str(approval.get("fingerprint") or "").lower()
            or oid not in str(approval["reply"]).lower()):
        raise TicketError("no recorded confirmation of this exact order ID: a simulated buy or sell is never "
                          "recorded without it")
    if side not in ("buy", "sell"):
        raise TicketError("side must be buy or sell")
    pf = read_json(portfolio_path, "portfolio", required=False)
    if pf is None:
        pf = {"simulated": True, "currency": "USD", "starting_capital_usd": SIM_CAPITAL_USD,
              "cash": float(cfg["budget"]), "positions": []}
    symbol = symbol.upper()
    qty, price = float(qty), float(price)
    if qty <= 0 or price <= 0:
        raise TicketError("a fill needs a positive qty and price")
    cost = round(qty * price, 2)
    pos = None
    for p in pf.setdefault("positions", []):
        if str(p.get("ticker", "")).upper() == symbol:
            pos = p
    if side == "buy":
        if cost > float(pf.get("cash", 0)) + 0.005:
            raise TicketError("cannot record buying %s %s for %s: the simulated cash is %s (no margin)"
                              % (_str_num(qty), symbol, _money(cost), _money(pf.get("cash", 0))))
        if pos is None:
            pos = {"ticker": symbol, "shares": 0.0, "lots": []}
            pf["positions"].append(pos)
        lots = pos.setdefault("lots", [])
        lots.append({"id": "%s-%d" % (symbol, len(lots) + 1), "date": date, "shares": qty, "cost": cost})
        pos["shares"] = round(float(pos.get("shares", 0)) + qty, 6)
        pf["cash"] = round(float(pf.get("cash", 0)) - cost, 2)
    else:
        if pos is None or float(pos.get("shares", 0)) + 1e-9 < qty:
            raise TicketError("cannot record selling %s %s: the portfolio holds %s (no short selling)"
                              % (_str_num(qty), symbol, pos.get("shares", 0) if pos else 0))
        left = qty
        for lot in sorted(pos.get("lots", []), key=lambda l: l.get("date", "")):
            if left <= 1e-9:
                break
            take = min(left, float(lot["shares"]))
            per = float(lot["cost"]) / float(lot["shares"]) if float(lot["shares"]) else 0
            lot["cost"] = round(float(lot["cost"]) - per * take, 2)
            lot["shares"] = round(float(lot["shares"]) - take, 6)
            left -= take
        pos["lots"] = [l for l in pos.get("lots", []) if float(l["shares"]) > 1e-9]
        pos["shares"] = round(float(pos["shares"]) - qty, 6)
        if pos["shares"] <= 1e-9:
            pf["positions"].remove(pos)
        pf["cash"] = round(float(pf.get("cash", 0)) + cost, 2)
    pf["simulated"] = True
    write_json(portfolio_path, pf)
    return pf


def log_fill(state_path, now, today, symbol, side, qty, price):
    """A fill in the log, so trader-risk can count day trades (a buy and a sell the same day)."""
    state = load_state(state_path)
    state.setdefault("orders", []).append({
        "at": ny_iso(now), "date": today, "status": "filled", "symbol": symbol.upper(), "side": side,
        "qty": _str_num(float(qty)), "price": float(price),
        "plain": "%s %s %s at %s" % (side.upper(), _str_num(float(qty)), symbol.upper(), _p(price))})
    write_json(state_path, state)


# ---------------------------------------------------------------- commands

def _clock(a):
    now = parse_now(getattr(a, "now", None))
    today = getattr(a, "today", None) or to_eastern(now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", today):
        raise TicketError("--today wants a date like 2026-10-19")
    return now, today


def require_sim(config_path):
    """Read the config and refuse to go on unless it is a USD 1,000 simulation."""
    cfg = read_json(config_path, "config", required=False) or {}
    bad = sim_config_violations(cfg)
    if bad:
        raise TicketError("simulation guard: " + "; ".join(bad) + ". Real-money trading is not supported here.")
    return cfg


def _load(a):
    doc = read_json(a.orders, "orders file (run trader-budget, or ticket.py flatten, first)")
    orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
    if not isinstance(orders, list) or not orders:
        raise TicketError("no orders in %s" % a.orders)
    cfg = require_sim(a.config)
    for o in orders:
        bad = sim_order_violations(o, doc)
        if bad:
            raise TicketError("order refused, it is not part of the simulation: " + "; ".join(bad))
    risk = read_json(a.risk, "risk check", required=False)
    state = load_state(a.state)
    now, today = _clock(a)
    return orders, cfg, risk, state, today, now


def _pick(orders, index):
    if index is None:
        raise TicketError("say which order: --index N")
    if not 1 <= index <= len(orders):
        raise TicketError("there is no order %d (there are %d)" % (index, len(orders)))
    return orders[index - 1]


def cmd_show(a):
    orders, cfg, risk, state, today, now = _load(a)
    picks = [(a.index, _pick(orders, a.index))] if a.index else list(enumerate(orders, 1))
    if a.json:
        out = [ticket_json(o, i, cfg, risk, state, today) for i, o in picks]
        print(json.dumps(out[0] if a.index else out, indent=2))
        return 0 if any(t["ready"] for t in out) else 1
    blocks, any_ready = [], False
    for i, o in picks:
        text, ready = render(o, i, len(orders), cfg, risk, state, today)
        blocks.append(text)
        any_ready = any_ready or ready
    print("\n\n".join(blocks))
    print("\nOne order at a time: a confirmation covers one order ID, never the batch. SIMULATION with pretend money. "
          "Education and tooling, not financial advice.")
    return 0 if any_ready else 1


def cmd_approve(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    ready, label, rv = status_of(order, risk, state, today)
    if not ready:
        raise TicketError("order %d is not ready: %s" % (a.index, label))
    ok, why = parse_yes(a.reply, order, orders)
    if not ok:
        print("Not recorded: %s. Show the user the ticket for order %d again; do not fill in the ID for them." % (why, a.index))
        return 1
    loss, stop = max_loss(order)
    rec = {"at": ny_iso(now), "date": today, "index": a.index, "fingerprint": fingerprint(order),
           "symbol": str(order.get("symbol", "")).upper(), "side": order.get("side"),
           "qty": order.get("qty"), "kind": kind_of(order, rv), "max_loss": loss, "stop": stop,
           "plain": plain(order), "status": "approved", "reply": a.reply, "confirmed_id": fingerprint(order),
           "simulated": True}
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Recorded your confirmation of order ID %s: %s (SIMULATED)." % (fingerprint(order), plain(order)))
    print("Nothing was sent anywhere. Now record the simulated fill at a market price:")
    print("  ticket.py result --index %d --status placed --filled-qty Q --filled-price P" % a.index)
    return 0


def cmd_decline(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    rec = {"at": ny_iso(now), "date": today, "index": a.index, "fingerprint": fingerprint(order),
           "symbol": str(order.get("symbol", "")).upper(), "side": order.get("side"),
           "plain": plain(order), "status": "declined", "reply": a.reply or "no"}
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Recorded: you said no to order %d (%s). Nothing was sent." % (a.index, plain(order)))
    return 0


def cmd_result(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    fp = fingerprint(order)
    rec = latest(state, fp, today)
    if not rec or rec.get("status") != "approved":
        raise TicketError("order %d has no confirmation recorded today; a simulated fill can only follow \"yes <order ID>\"" % a.index)
    new = {"at": ny_iso(now), "date": today, "index": a.index, "fingerprint": fp, "symbol": rec["symbol"],
           "side": rec["side"], "plain": rec["plain"], "status": a.status, "simulated": True}
    for k in ("qty", "kind", "max_loss", "stop"):
        if rec.get(k) is not None:
            new[k] = rec[k]
    if a.note:
        new["note"] = a.note
    if a.status == "placed":
        if not (a.filled_qty and a.filled_price):
            raise TicketError("a simulated fill needs --filled-qty and --filled-price (a market price)")
        ordered = _f(order.get("qty"))
        if ordered is not None and _f(a.filled_qty) is not None and _f(a.filled_qty) > ordered + 1e-9:
            raise TicketError("the fill (%s) is bigger than the approved order (%s)" % (a.filled_qty, order.get("qty")))
        # the portfolio is touched first: if it refuses (no cash, no shares), nothing is logged as filled
        apply_fill(a.portfolio, cfg, rec["symbol"], rec["side"], a.filled_qty, a.filled_price, today, approval=rec)
    state["orders"].append(new)
    write_json(a.state, state)
    print("Recorded order %d as %s (SIMULATED)." % (a.index, a.status))
    if a.status == "placed":
        log_fill(a.state, now, today, rec["symbol"], rec["side"], a.filled_qty, a.filled_price)
        print("Added the simulated fill to %s." % a.portfolio)
    return 0


def cmd_flatten(a):
    cfg = require_sim(a.config)
    sym = a.symbol.strip().upper()
    if not _sim_ticker_ok(sym):
        raise TicketError("%r is not a plain US stock ticker" % a.symbol)
    now, today = _clock(a)
    source = a.portfolio
    pf = read_json(a.portfolio, "portfolio", required=False) or {}
    held = sum(_f(p.get("shares", p.get("qty"))) or 0 for p in pf.get("positions", [])
               if str(p.get("ticker") or p.get("symbol") or "").upper() == sym)
    if held <= 1e-9:
        raise TicketError("nothing to flatten: no simulated %s shares in %s" % (sym, a.portfolio))
    qty = held
    if a.qty is not None:
        qty = _f(a.qty)
        if qty is None or qty <= 0:
            raise TicketError("--qty wants a number of shares, like --qty 8")
        if qty > held + 1e-9:
            raise TicketError("you hold %s simulated %s shares; selling %s would be a short sale" %
                              (_str_num(held), sym, _str_num(qty)))
    plan = read_json(a.plan, "plan", required=False) or {}
    flat_by = (plan.get("flat_by") if str(plan.get("symbol", "")).upper() == sym else None) \
        or cfg.get("flat_by") or "15:55"
    order = {"symbol": sym, "side": "sell", "qty": _str_num(qty), "type": "market", "time_in_force": "day",
             "why": "flat by %s New York: closes the %s day trade before the close (qty from %s)"
             % (flat_by, sym, source)}
    old = read_json(a.orders, "orders", required=False)
    replaced = len(old.get("orders", [])) if isinstance(old, dict) else 0
    doc = {"created_by": "trader-broker", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "proposed",
           "paper": True, "simulated": True,
           "note": "Simulated flatten ticket. Nothing is recorded until trader-risk passes it and you say yes in the chat.",
           "source": "ticket.py flatten %s on %s" % (sym, today), "orders": [order]}
    write_json(a.orders, doc)
    print("Flatten %s: %s (flat by %s New York)." % (sym, plain(order), flat_by))
    print("Wrote it to %s%s." % (a.orders, (" (it replaced %d earlier proposal%s)"
                                             % (replaced, "" if replaced == 1 else "s")) if replaced else ""))
    print("Next:")
    print("  1. trader-risk: check.py. A sell that only closes what you hold is never blocked by the daily")
    print("     limits or the entry window.")
    print("  2. ticket.py show, then the user's \"yes <order ID>\" for this one order.")
    print("  3. ticket.py result --index 1 --status placed --filled-qty Q --filled-price P (simulated fill).")
    return 0


def cmd_log(a):
    state = load_state(a.state)
    now, today = _clock(a)
    rows = [r for r in state.get("orders", []) if a.all or rec_day(r) == today]
    if not rows:
        print("No decisions recorded%s." % ("" if a.all else " today"))
        return 1
    for r in rows:
        extra = ""
        reply = (' reply "%s"' % r["reply"]) if r.get("reply") and r["status"] in ("approved", "declined") else ""
        loss = (" max loss %s" % _money(r["max_loss"])) if r.get("max_loss") is not None and r["status"] == "placed" else ""
        idx = ("#%s" % r["index"]) if r.get("index") is not None else "  "
        print("%s  %s %-9s %s%s%s%s" % (r.get("at"), idx, r.get("status"), r.get("plain"), reply, loss, extra))
    placed = sum(1 for r in rows if r.get("status") == "placed")
    print("%d simulated fill%s%s." % (placed, "" if placed == 1 else "s", "" if a.all else " today"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="SIMULATED order tickets and your yes (trader-broker). No broker, no real orders.")
    sub = ap.add_subparsers(dest="cmd")

    def clock(p):
        p.add_argument("--now", help="pretend it is this New York time, e.g. \"2026-10-19 10:15\"")
        p.add_argument("--today", help="YYYY-MM-DD (default: today in New York)")

    def common(p):
        p.add_argument("--orders", default="trader/orders.json")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--risk", default="trader/state/risk.json")
        p.add_argument("--state", default="trader/state/broker.json")
        clock(p)

    p = sub.add_parser("show", help="render the tickets")
    common(p)
    p.add_argument("--index", type=int)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("approve", help="record the user's explicit yes for one order")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply", required=True, help="the user's reply, word for word: yes <order ID>")
    p = sub.add_parser("decline", help="record a no")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply")
    p = sub.add_parser("result", help="record the SIMULATED fill of an order you said yes to")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--status", required=True, choices=["placed", "denied", "failed"])
    p.add_argument("--note")
    p.add_argument("--filled-qty")
    p.add_argument("--filled-price")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p = sub.add_parser("flatten", help="a sell ticket that closes a symbol's position by flat_by")
    p.add_argument("--symbol", required=True)
    p.add_argument("--qty", help="simulated shares to sell (default: all you hold; never more)")
    p.add_argument("--orders", default="trader/orders.json", help="where the ticket is written")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--config", default="trader/config.json")
    clock(p)
    p = sub.add_parser("log", help="today's decisions")
    p.add_argument("--state", default="trader/state/broker.json")
    clock(p)
    p.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"show": cmd_show, "approve": cmd_approve, "decline": cmd_decline, "result": cmd_result,
                "flatten": cmd_flatten, "log": cmd_log}[a.cmd](a)
    except TicketError as e:
        print("ticket.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
