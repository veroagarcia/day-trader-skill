import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX, SKILLS

ticket = load("trader-broker", "ticket")
check = load("trader-risk", "check")
ticket.SIM_CAPITAL_USD = check.SIM_CAPITAL_USD = 5000.0  # test only: the reel uses a $5,000 account (see test_simulation.py)

CFG_PATH = os.path.join(FIX, "reel-config.json")
ORDERS_PATH = os.path.join(FIX, "trader-risk", "orders-tsla.json")
PLAN_PATH = os.path.join(FIX, "trader-budget", "plan-tsla.json")
NOW = "2026-10-19 10:15"
TODAY = "2026-10-19"
AAPL = {"symbol": "AAPL", "side": "buy", "notional": "1250", "type": "market", "time_in_force": "day"}
BATCH = ["AAPL", "AXP", "GOOGL", "KO", "BAC"]
TSLA_CALL = {"symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
             "order_class": "bracket", "take_profit_limit_price": "370.04", "stop_loss_stop_price": "358.32"}
KO_SELL = {"symbol": "KO", "side": "sell", "qty": "2.5", "type": "market", "time_in_force": "day"}
TSLA_PLAIN = ("BUY 8 TSLA, market, good for today / stop-loss 358.32 / take-profit 370.04 / max loss about "
              "$46.88 if the stop fills at 358.32 (it can fill worse in a fast market)")


def tsla(**over):
    with open(ORDERS_PATH) as fh:
        o = json.load(fh)["orders"][0]
    o.update(over)
    return o


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ticket.main(argv)
    return code, out.getvalue(), err.getvalue()


def approval(order=None, **over):
    """A recorded confirmation for an order, the way ticket.py approve stores it."""
    fp = ticket.fingerprint(order or tsla())
    rec = {"status": "approved", "reply": "yes " + fp, "confirmed_id": fp, "fingerprint": fp}
    rec.update(over)
    return rec


class ExplicitConfirmation(unittest.TestCase):
    """Only "yes <order ID>" for THIS order counts. The ID is the order's fingerprint."""

    def ok(self, reply, order=AAPL, batch=()):
        return ticket.parse_yes(reply, order, batch)[0]

    def test_only_yes_plus_this_orders_id_counts(self):
        o = tsla()
        fid = ticket.fingerprint(o)
        for r in ("yes " + fid, "Yes " + fid, "YES " + fid.upper(), "  yes   %s  " % fid, "yes, " + fid,
                  "yes " + fid + ".", "confirm " + fid, "yes order " + fid, "yes order id " + fid, "yes #" + fid):
            self.assertTrue(self.ok(r, o), r)
        self.assertEqual(ticket.confirmation_text(o), "yes " + fid)

    def test_generic_or_vague_replies_never_count(self):
        o = tsla()
        fid = ticket.fingerprint(o)
        for r in ("", "yes", "y", "Yes.", "sure", "ok", "okay", "go", "do it", "yeah", "send it",
                  "yes to all", "yes, all of them", "yes to the rest", "yes both", "yes everything",
                  "yes TSLA", "yes 8 TSLA", "yes 358.32", "yes sell 8", "yes?", "no", "no " + fid, "not yes " + fid,
                  "yes but " + fid, "yes " + fid + " and the rest", "yes " + fid + " all", fid, "yes " + fid[:8],
                  "yes " + fid + "0", "yes 0000000000000000", "yes " + fid + " or " + fid):
            self.assertFalse(self.ok(r, o), r)

    def test_the_id_of_another_order_does_not_count(self):
        a, b = tsla(), dict(tsla(), qty="4")
        self.assertNotEqual(ticket.fingerprint(a), ticket.fingerprint(b))
        ok, why = ticket.parse_yes("yes " + ticket.fingerprint(b), a, [a, b])
        self.assertFalse(ok)
        self.assertIn("different order", why)
        ok, why = ticket.parse_yes("yes " + ticket.fingerprint(a), b, [a, b])
        self.assertFalse(ok)

    def test_editing_the_order_changes_its_id(self):
        o = tsla()
        old = ticket.confirmation_text(o)
        edited = dict(o, qty="9")
        self.assertFalse(self.ok(old, edited))

    def test_the_ticket_prints_the_id_and_the_exact_reply(self):
        o = tsla()
        text, ready = ticket.render(o, 1, 1, {}, {"date": TODAY, "results": [
            {"fingerprint": ticket.fingerprint(o), "verdict": "PASS", "reasons": []}]}, {"orders": []}, TODAY)
        self.assertTrue(ready)
        self.assertIn("order ID: " + ticket.fingerprint(o), text)
        self.assertIn("reply exactly: " + ticket.confirmation_text(o), text)


class TicketShape(unittest.TestCase):
    def test_tool_input_is_the_alpaca_call(self):
        o = dict(AAPL, why="from a list")
        self.assertEqual(ticket.tool_input(o), AAPL)
        self.assertEqual(ticket.tool_input({"symbol": "KO", "side": "buy", "qty": 3, "type": "limit",
                                            "limit_price": 89.5, "time_in_force": "day"}),
                         {"symbol": "KO", "side": "buy", "qty": "3", "type": "limit", "limit_price": "89.5",
                          "time_in_force": "day"})

    def test_the_bracket_call_leaves_out_why_and_plan(self):
        self.assertEqual(ticket.tool_input(tsla()), TSLA_CALL)
        self.assertEqual(ticket.fingerprint(tsla()), ticket.fingerprint(TSLA_CALL))

    def test_plain_english(self):
        self.assertEqual(ticket.plain(AAPL), "BUY $1,250 of AAPL, market order, good for today")
        self.assertEqual(ticket.plain({"symbol": "KO", "side": "sell", "qty": "1", "type": "limit",
                                       "limit_price": "95", "time_in_force": "gtc"}),
                         "SELL 1 share of KO, limit order at $95, good until canceled")
        self.assertEqual(ticket.plain(tsla()), TSLA_PLAIN)
        lim = tsla(type="limit", limit_price="364.00")
        self.assertEqual(ticket.plain(lim).split(" / ")[0], "BUY 8 TSLA, limit 364.00, good for today")
        self.assertEqual(ticket.max_loss(lim), (45.44, 358.32))
        no_plan = dict(TSLA_CALL)
        self.assertEqual(ticket.max_loss(no_plan), (None, 358.32))


class Flow(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.orders = os.path.join(self.d, "orders.json")
        shutil.copy(ORDERS_PATH, self.orders)
        self.cfg = os.path.join(self.d, "config.json")
        shutil.copy(CFG_PATH, self.cfg)
        self.risk = os.path.join(self.d, "state", "risk.json")
        self.state = os.path.join(self.d, "state", "broker.json")
        self.pf = os.path.join(self.d, "portfolio.json")
        self.none = os.path.join(self.d, "none")

    def tearDown(self):
        shutil.rmtree(self.d)

    def args(self, *extra, **kw):
        return list(extra) + ["--orders", self.orders, "--config", self.cfg, "--risk", self.risk,
                              "--state", self.state, "--now", kw.get("now", NOW)]

    def run_risk(self, now=NOW):
        with redirect_stdout(io.StringIO()):
            return check.main(["--orders", self.orders, "--config", self.cfg, "--portfolio", self.pf,
                               "--prices", self.none, "--state", self.state, "--now", now, "--out", self.risk])

    def state_doc(self):
        with open(self.state) as fh:
            return json.load(fh)

    def conf(self, index=1):
        """The exact confirmation the ticket asks for: yes + that order's ID."""
        with open(self.orders) as fh:
            doc = json.load(fh)
        return ticket.confirmation_text(doc["orders"][index - 1])

    def test_nothing_is_ready_before_the_risk_check(self):
        code, text, _ = run(self.args("show"))
        self.assertEqual(code, 1)
        self.assertIn("NOT READY", text)
        self.assertNotIn("Reply \"yes\"", text)
        code, _, err = run(self.args("approve", "--index", "1", "--reply", self.conf()))
        self.assertEqual(code, 1)
        self.assertIn("not ready", err)

    def test_the_full_two_yes_flow(self):
        self.assertEqual(self.run_risk(), 0)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 0)
        self.assertIn("ORDER 1 of 1, SIMULATED", text)
        for part in TSLA_PLAIN.split(" / "):
            self.assertIn("  " + part + "\n", text)
        self.assertIn("READY: trader-risk PASS", text)
        self.assertNotIn("place_stock_order", text)
        self.assertNotIn("Allow once", text)
        self.assertIn("SIMULATED order", text)

        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "sure"))
        self.assertEqual(code, 1)
        self.assertIn("Not recorded", text)
        self.assertFalse(os.path.exists(self.state))

        code, text, _ = run(self.args("approve", "--index", "1", "--reply", self.conf()))
        self.assertEqual(code, 0)
        self.assertIn("SIMULATED", text)
        self.assertIn("Nothing was sent anywhere", text)
        self.assertNotIn("place_stock_order", text)
        code, _, err = run(self.args("approve", "--index", "1", "--reply", self.conf()))
        self.assertEqual(code, 1)
        self.assertIn("APPROVED", err)

        code, text, _ = run(self.args("result", "--index", "1", "--status", "placed",
                                      "--filled-qty", "8", "--filled-price", "364.20", "--portfolio", self.pf,
                                      now="2026-10-19 10:16"))
        self.assertEqual(code, 0)
        st = self.state_doc()
        self.assertEqual([r["status"] for r in st["orders"]], ["approved", "placed", "filled"])
        appr, plc = st["orders"][0], st["orders"][1]
        self.assertEqual((appr["reply"], appr["kind"], appr["max_loss"], appr["date"]),
                         (ticket.confirmation_text(tsla()), "entry", 46.88, TODAY))
        self.assertEqual(appr["confirmed_id"], ticket.fingerprint(tsla()))
        self.assertEqual(appr["at"], "2026-10-19T10:15:00-04:00")
        self.assertEqual((plc["max_loss"], plc["kind"], plc["simulated"]), (46.88, "entry", True))
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual(pf["cash"], 2086.4)
        self.assertEqual(pf["positions"][0]["shares"], 8)

        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("DONE: placed", text)
        code, text, _ = run(["log", "--state", self.state, "--now", NOW])
        self.assertIn("1 simulated fill today", text)
        self.assertIn("max loss $46.88", text)

        # trader-risk now counts it: a second TSLA buy today is a duplicate, and $46.88 is used
        res = check.check([tsla()], {"budget": 5000}, state=st, now=check.parse_now("2026-10-19 10:30"))
        self.assertIn("already placed today", " ".join(res["results"][0]["reasons"]))
        self.assertEqual((res["today"]["entries_placed"], res["today"]["loss_at_risk"]), (1, 46.88))

    def test_flatten_by_the_close(self):
        self.run_risk()
        run(self.args("approve", "--index", "1", "--reply", self.conf()))
        run(self.args("result", "--index", "1", "--status", "placed",
                      "--filled-qty", "8", "--filled-price", "364.20", "--portfolio", self.pf))
        late = "2026-10-19 15:55"
        code, text, _ = run(["flatten", "--symbol", "TSLA", "--orders", self.orders, "--portfolio", self.pf,
                             "--plan", PLAN_PATH, "--config", self.cfg, "--now", late])
        self.assertEqual(code, 0)
        self.assertIn("SELL 8 shares of TSLA, market order, good for today (flat by 15:55 New York)", text)
        self.assertIn("replaced 1 earlier proposal", text)
        with open(self.orders) as fh:
            doc = json.load(fh)
        self.assertEqual(ticket.tool_input(doc["orders"][0]),
                         {"symbol": "TSLA", "side": "sell", "qty": "8", "type": "market", "time_in_force": "day"})
        self.assertEqual(self.run_risk(now=late), 0)       # after the 15:30 entry cutoff: an exit still passes
        with open(self.risk) as fh:
            self.assertEqual(json.load(fh)["results"][0]["kind"], "exit")
        code, text, _ = run(self.args("show", now=late))
        self.assertEqual(code, 0)
        self.assertIn("READY", text)
        self.assertEqual(run(self.args("approve", "--index", "1", "--reply", self.conf(), now=late))[0], 0)
        code, _, _ = run(self.args("result", "--index", "1", "--status", "placed", "--filled-qty", "8",
                                   "--filled-price", "366.10", "--portfolio", self.pf, now="2026-10-19 15:56"))
        self.assertEqual(code, 0)
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual((pf["cash"], pf["positions"]), (5015.2, []))
        self.assertEqual(check.day_trades(self.state_doc(), TODAY), (1, ["2026-10-19 TSLA"]))
        code, _, err = run(["flatten", "--symbol", "TSLA", "--orders", self.orders, "--portfolio", self.pf,
                            "--config", self.cfg, "--now", late])
        self.assertEqual(code, 1)
        self.assertIn("nothing to flatten", err)

    def test_flatten_cannot_sell_what_the_simulation_does_not_hold(self):
        code, _, err = run(["flatten", "--symbol", "tsla", "--qty", "8", "--orders", self.orders,
                            "--portfolio", self.none, "--plan", self.none, "--config", self.cfg, "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("nothing to flatten", err)
        with open(self.pf, "w") as fh:
            json.dump({"simulated": True, "cash": 0, "positions": [{"ticker": "TSLA", "shares": 3, "lots": []}]}, fh)
        code, _, err = run(["flatten", "--symbol", "TSLA", "--qty", "8", "--orders", self.orders,
                            "--portfolio", self.pf, "--config", self.cfg, "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("short sale", err)

    def test_an_edited_order_is_not_ready(self):
        self.run_risk()
        with open(self.orders) as fh:
            doc = json.load(fh)
        doc["orders"][0]["qty"] = "9"
        with open(self.orders, "w") as fh:
            json.dump(doc, fh)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 1)
        self.assertIn("was not in the last risk check", text)

    def test_yesterdays_check_does_not_count(self):
        self.run_risk(now="2026-10-16 10:15")
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("not today", text)

    def test_blocked_orders_are_never_ready(self):
        self.assertEqual(self.run_risk(now="2026-10-19 09:40"), 1)
        code, text, _ = run(self.args("show", "--index", "1", now="2026-10-19 09:40"))
        self.assertIn("BLOCKED by trader-risk: window: no new entries before 09:45", text)
        code, _, _ = run(self.args("approve", "--index", "1", "--reply", self.conf(), now="2026-10-19 09:40"))
        self.assertEqual(code, 1)

    def test_result_needs_an_approval_and_decline_is_logged(self):
        self.run_risk()
        code, _, err = run(self.args("result", "--index", "1", "--status", "placed"))
        self.assertEqual(code, 1)
        self.assertIn("no confirmation recorded", err)
        code, text, _ = run(self.args("decline", "--index", "1", "--reply", "no thanks"))
        self.assertEqual(code, 0)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("DONE: declined", text)

    def test_a_broker_config_is_refused(self):
        with open(self.cfg) as fh:
            c = json.load(fh)
        c["broker"] = "ibkr"
        with open(self.cfg, "w") as fh:
            json.dump(c, fh)
        code, _, err = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 1)
        self.assertIn("simulation guard", err)

    def test_fill_sell_relieves_the_oldest_lot(self):
        pf = {"simulated": True, "cash": 0, "positions": [{"ticker": "KO", "shares": 3, "lots": [
            {"id": "KO-1", "date": "2025-01-02", "shares": 2, "cost": 120.0},
            {"id": "KO-2", "date": "2026-01-02", "shares": 1, "cost": 70.0}]}]}
        with open(self.pf, "w") as fh:
            json.dump(pf, fh)
        yes = approval(dict(KO_SELL))
        with open(self.cfg) as fh:
            cfg = json.load(fh)
        ticket.apply_fill(self.pf, cfg, "KO", "sell", "2.5", "90", TODAY, approval=yes)
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual(pf["cash"], 225.0)
        lots = pf["positions"][0]["lots"]
        self.assertEqual([l["id"] for l in lots], ["KO-2"])
        self.assertEqual(lots[0]["shares"], 0.5)
        self.assertEqual(lots[0]["cost"], 35.0)
        with self.assertRaises(ticket.TicketError):          # no short selling
            ticket.apply_fill(self.pf, cfg, "KO", "sell", "5", "90", TODAY, approval=yes)


if __name__ == "__main__":
    unittest.main()
