"""Simulation-only guarantees: USD 1,000 of pretend money, no broker, no real orders, a yes for every trade.

These tests use the REAL constants (nothing patched), the shipped trader/config.json and temp folders.
They never touch the network."""

import copy
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, ROOT, SKILLS, load

ticket = load("trader-broker", "ticket")
check = load("trader-risk", "check")
size = load("trader-budget", "size")
MODULES = (ticket, check, size)
SHIPPED = os.path.join(ROOT, "trader", "config.json")
ORDERS = os.path.join(FIX, "trader-risk", "orders-tsla.json")
PLAN = os.path.join(FIX, "trader-budget", "plan-tsla.json")
NOW = "2026-10-19 10:15"
TODAY = "2026-10-19"

REAL_MONEY_REQUESTS = {
    "paper turned off": {"paper": False},
    "live mode": {"mode": "live"},
    "no mode": {"mode": None},
    "alpaca broker": {"broker": "alpaca"},
    "ibkr broker": {"broker": "ibkr"},
    "margin on": {"allow_margin": True},
    "options on": {"allow_options": True},
    "short selling on": {"allow_short": True},
    "margin unset": {"allow_margin": None},
    "budget above 1000": {"budget": 5000},
    "budget zero": {"budget": 0},
    "capital above 1000": {"sim_capital_usd": 5000},
    "api key in config": {"ALPACA_API_KEY": "x"},
    "secret in config": {"api_secret": "x"},
}


def shipped():
    with open(SHIPPED) as fh:
        return json.load(fh)


def cfg_with(**over):
    c = shipped()
    for k, v in over.items():
        if v is None:
            c.pop(k, None)
        else:
            c[k] = v
    return c


def call(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def small_orders(qty="1"):
    with open(ORDERS) as fh:
        doc = json.load(fh)
    doc["orders"][0]["qty"] = qty
    doc["orders"][0]["plan"]["max_loss"] = round(5.86 * int(qty), 2)
    return doc


PORTFOLIO_KEYS = {"simulated", "currency", "starting_capital_usd", "cash", "positions"}
POSITION_KEYS = {"ticker", "shares", "lots"}
LOT_KEYS = {"id", "date", "shares", "cost"}


def assert_clean_portfolio(tc, pf, where):
    """Only the simulated-account fields, and nothing that looks like an email, a token or a local path."""
    tc.assertLessEqual(set(pf), PORTFOLIO_KEYS, where)
    for pos in pf["positions"]:
        tc.assertLessEqual(set(pos), POSITION_KEYS, where)
        for lot in pos.get("lots", []):
            tc.assertLessEqual(set(lot), LOT_KEYS, where)
    blob = json.dumps(pf)
    tc.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", blob), where)
    tc.assertIsNone(re.search(r"[A-Za-z0-9+/_-]{24,}", blob), where)
    tc.assertNotIn("/home/", blob, where)
    tc.assertNotIn("\\Users\\", blob, where)


class ShippedProject(unittest.TestCase):
    def test_shipped_config_is_the_1000_dollar_simulation(self):
        c = shipped()
        for m in MODULES:
            self.assertEqual(m.sim_config_violations(c), [], m.__name__)
            self.assertEqual(m.SIM_CAPITAL_USD, 1000.0)
        self.assertEqual((c["mode"], c["paper"], c["broker"], c["budget"], c["sim_capital_usd"]),
                         ("simulation", True, "none", 1000, 1000))
        for k in ("allow_margin", "allow_options", "allow_short"):
            self.assertIs(c[k], False, k)
        self.assertIs(c["require_stop"], True)

    def test_example_config_is_the_same_simulation(self):
        with open(os.path.join(SKILLS, "trader-budget", "config.example.json")) as fh:
            self.assertEqual(json.load(fh), shipped())

    def test_starting_portfolio_is_1000_simulated_dollars(self):
        with open(os.path.join(ROOT, "trader", "portfolio.json")) as fh:
            pf = json.load(fh)
        self.assertEqual((pf["simulated"], pf["currency"], pf["cash"], pf["positions"]), (True, "USD", 1000, []))

    def test_the_three_guard_copies_are_identical(self):
        blocks = []
        for folder, name in (("trader-broker", "ticket"), ("trader-risk", "check"), ("trader-budget", "size")):
            with open(os.path.join(SKILLS, folder, name + ".py"), encoding="utf-8") as fh:
                src = fh.read()
            m = re.search(r"# ==== BEGIN simulation guard.*?# ==== END simulation guard ====", src, re.S)
            self.assertIsNotNone(m, name)
            blocks.append(m.group(0))
        self.assertEqual(blocks[0], blocks[1])
        self.assertEqual(blocks[0], blocks[2])

    def test_portfolio_and_logs_hold_no_credentials_or_sensitive_data(self):
        with open(os.path.join(ROOT, "trader", "portfolio.json")) as fh:
            assert_clean_portfolio(self, json.load(fh), "trader/portfolio.json")
        for f in sorted(os.listdir(os.path.join(ROOT, "trader"))):
            path = os.path.join(ROOT, "trader", f)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text), f)
                self.assertIsNone(re.search(r"(?i)api[_-]?key|secret|token|password|passwd|bearer", text), f)

    def test_no_broker_connector_credentials_or_personal_data(self):
        banned_files = ("claude_desktop_config.example.json", ".mcp.json")
        secret = re.compile(r"ALPACA_(API|SECRET)_KEY|\bPK[A-Z0-9]{18,}\b|\bAKIA[A-Z0-9]{12,}\b|uvx\s+alpaca|"
                            r"place_stock_order\s*\(|alpaca-mcp-server\"")
        email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "fixtures")]
            for f in files:
                self.assertNotIn(f, banned_files)
                path = os.path.join(base, f)
                rel = os.path.relpath(path, ROOT)
                if not f.endswith((".md", ".py", ".json", ".txt")):
                    continue
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                if not rel.startswith("tests"):
                    self.assertIsNone(secret.search(text), rel)
                if rel.startswith("trader") and not rel.startswith(os.path.join(".claude", "skills")) \
                        or rel.endswith("config.example.json") or rel == os.path.join(".claude", "settings.json"):
                    self.assertIsNone(email.search(text), rel)

    def test_skill_instructions_have_no_broker_setup(self):
        for s in sorted(os.listdir(SKILLS)):
            with open(os.path.join(SKILLS, s, "SKILL.md"), encoding="utf-8") as fh:
                text = fh.read()
            for bad in ("place_stock_order", "Needs approval", "Allow once", "uvx", "ALPACA_PAPER_TRADE",
                        "get_open_position", "cancel_order_by_id", "Going live is the user's own decision"):
                self.assertNotIn(bad, text, "%s mentions %s" % (s, bad))
            if s in ("trader-broker", "trader-budget", "trader-risk"):
                self.assertIn("SIMULATION", text, s)

    def test_project_settings_block_brokers_and_ask_before_recording(self):
        with open(os.path.join(ROOT, ".claude", "settings.json")) as fh:
            perms = json.load(fh)["permissions"]
        for rule in ("mcp__alpaca", "mcp__alpaca__*", "mcp__ibkr", "mcp__ibkr__*"):
            self.assertIn(rule, perms["deny"])
        self.assertIn("Bash(python3 *ticket.py approve*)", perms["ask"])
        self.assertIn("Bash(python3 *ticket.py result*)", perms["ask"])


class RealMoneyIsRefused(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.orders = os.path.join(self.d, "orders.json")
        with open(self.orders, "w") as fh:
            json.dump(small_orders(), fh)
        self.cfg = os.path.join(self.d, "config.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def write_cfg(self, c):
        with open(self.cfg, "w") as fh:
            json.dump(c, fh)

    def test_every_real_money_config_has_violations_in_every_tool(self):
        for label, over in REAL_MONEY_REQUESTS.items():
            for m in MODULES:
                self.assertTrue(m.sim_config_violations(cfg_with(**over)), "%s / %s" % (label, m.__name__))
        for m in MODULES:
            self.assertTrue(m.sim_config_violations({}))
            self.assertTrue(m.sim_config_violations(None))

    def test_every_tool_refuses_to_run_on_a_real_money_config(self):
        for label, over in REAL_MONEY_REQUESTS.items():
            self.write_cfg(cfg_with(**over))
            runs = (
                (ticket.main, ["show", "--orders", self.orders, "--config", self.cfg, "--now", NOW]),
                (ticket.main, ["approve", "--index", "1", "--reply", "yes 0000000000000000", "--orders", self.orders,
                               "--config", self.cfg, "--now", NOW]),
                (ticket.main, ["flatten", "--symbol", "TSLA", "--orders", self.orders, "--config", self.cfg]),
                (check.main, ["--orders", self.orders, "--config", self.cfg, "--no-write", "--now", NOW]),
                (size.main, ["--plan", PLAN, "--config", self.cfg, "--now", NOW]),
            )
            for main, argv in runs:
                code, _, err = call(main, argv)
                self.assertEqual(code, 1, "%s: %s" % (label, argv[0]))
                self.assertIn("simulation guard", err, "%s: %s" % (label, argv[0]))

    def test_a_missing_config_is_refused_not_defaulted(self):
        none = os.path.join(self.d, "nope.json")
        self.assertEqual(call(ticket.main, ["show", "--orders", self.orders, "--config", none])[0], 1)
        self.assertEqual(call(check.main, ["--orders", self.orders, "--config", none, "--no-write"])[0], 1)
        self.assertEqual(call(size.main, ["--plan", PLAN, "--config", none, "--now", NOW])[0], 1)

    def test_the_budget_cannot_be_raised_from_the_command_line(self):
        code, _, err = call(size.main, ["--plan", PLAN, "--config", SHIPPED, "--now", NOW, "--budget", "5000"])
        self.assertEqual(code, 1)
        self.assertIn("simulation guard", err)

    def test_options_crypto_and_odd_orders_are_refused(self):
        self.write_cfg(shipped())
        for sym in ("TSLA261016C00400000", "BTC/USD", "BTCUSD1", "", "TOOLONGSYM"):
            doc = small_orders()
            doc["orders"][0]["symbol"] = sym
            with open(self.orders, "w") as fh:
                json.dump(doc, fh)
            for main, argv in ((ticket.main, ["show", "--orders", self.orders, "--config", self.cfg]),
                               (check.main, ["--orders", self.orders, "--config", self.cfg, "--no-write"])):
                code, _, err = call(main, argv)
                self.assertEqual(code, 1, sym)
                self.assertIn("simulation guard" if main is check.main else "not part of the simulation", err)
        doc = small_orders()
        doc["orders"][0]["order_class"] = "oco"
        self.assertTrue(ticket.sim_order_violations(doc["orders"][0]))
        doc = small_orders()
        doc["paper"] = False
        self.assertTrue(ticket.sim_order_violations(doc["orders"][0], doc))
        for ok in ("AAPL", "brk.b", "BF-B"):
            self.assertEqual(ticket.sim_order_violations({"symbol": ok, "side": "buy"}), [], ok)

    def test_the_portfolio_has_one_door_and_it_needs_a_yes(self):
        pf = os.path.join(self.d, "portfolio.json")
        c = shipped()
        fp = "0123456789abcdef"
        for approval in (None, {}, {"status": "declined", "reply": "no"}, {"status": "approved"},
                         {"status": "approved", "reply": "yes", "confirmed_id": fp, "fingerprint": fp},
                         {"status": "approved", "reply": "yes " + fp, "confirmed_id": fp},
                         {"status": "approved", "reply": "yes " + fp, "confirmed_id": fp, "fingerprint": "f" * 16}):
            with self.assertRaises(ticket.TicketError):
                ticket.apply_fill(pf, c, "TSLA", "buy", 1, 364.2, TODAY, approval=approval)
        self.assertFalse(os.path.exists(pf))
        with self.assertRaises(ticket.TicketError):          # real-money config, even with a yes
            ticket.apply_fill(pf, cfg_with(paper=False), "TSLA", "buy", 1, 364.2, TODAY,
                              approval={"status": "approved", "reply": "yes " + fp, "confirmed_id": fp,
                                        "fingerprint": fp})
        self.assertFalse(os.path.exists(pf))

    def test_no_margin_and_no_short_in_the_portfolio(self):
        pf = os.path.join(self.d, "portfolio.json")
        fp = "0123456789abcdef"
        yes = {"status": "approved", "reply": "yes " + fp, "confirmed_id": fp, "fingerprint": fp}
        with self.assertRaises(ticket.TicketError) as cm:     # $1,500 of stock with $1,000 of cash
            ticket.apply_fill(pf, shipped(), "TSLA", "buy", 4, 375.0, TODAY, approval=yes)
        self.assertIn("no margin", str(cm.exception))
        self.assertFalse(os.path.exists(pf))
        with self.assertRaises(ticket.TicketError) as cm:     # selling what is not held
            ticket.apply_fill(pf, shipped(), "TSLA", "sell", 1, 375.0, TODAY, approval=yes)
        self.assertIn("no short", str(cm.exception))


class SimulatedTradeNeedsYes(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        j = lambda *p: os.path.join(self.d, *p)
        self.orders, self.cfg, self.pf = j("orders.json"), j("config.json"), j("portfolio.json")
        self.risk, self.state, self.none = j("state", "risk.json"), j("state", "broker.json"), j("none")
        shutil.copy(SHIPPED, self.cfg)
        shutil.copy(os.path.join(ROOT, "trader", "portfolio.json"), self.pf)
        self.write_orders(small_orders("1"))

    def tearDown(self):
        shutil.rmtree(self.d)

    def write_orders(self, doc):
        with open(self.orders, "w") as fh:
            json.dump(doc, fh)

    def tk(self, *argv):
        return call(ticket.main, list(argv) + ["--orders", self.orders, "--config", self.cfg, "--risk", self.risk,
                                               "--state", self.state, "--now", NOW])

    def result(self, *extra):
        return self.tk("result", "--index", "1", "--status", "placed", "--filled-qty", "1",
                       "--filled-price", "364.20", "--portfolio", self.pf, *extra)

    def conf(self):
        with open(self.orders) as fh:
            return ticket.confirmation_text(json.load(fh)["orders"][0])

    def run_risk(self):
        return call(check.main, ["--orders", self.orders, "--config", self.cfg, "--portfolio", self.pf,
                                 "--prices", self.none, "--state", self.state, "--now", NOW, "--out", self.risk])

    def portfolio(self):
        with open(self.pf) as fh:
            return json.load(fh)

    def test_nothing_is_recorded_without_the_risk_check_and_a_yes(self):
        before = self.portfolio()
        self.assertEqual(self.result()[0], 1)                       # no approval at all
        self.run_risk()
        self.assertEqual(self.result()[0], 1)                       # PASS, but still no yes
        for reply in ("", "yes", "Yes.", "sure", "ok", "do it", "yes to all", "yes?", "no", "yes TSLA", "yes 1",
                      "yes 0000000000000000", "yes " + self.conf()[4:] + " and the rest"):
            code, text, _ = self.tk("approve", "--index", "1", "--reply", reply)
            self.assertEqual(code, 1, reply)
            self.assertIn("Not recorded", text)
        self.assertEqual(self.result()[0], 1)                       # refused yeses recorded nothing
        self.assertFalse(os.path.exists(self.state))
        self.assertEqual(self.portfolio(), before)                  # still USD 1,000 and no positions

    def test_a_yes_without_a_risk_pass_is_not_accepted(self):
        code, _, err = self.tk("approve", "--index", "1", "--reply", self.conf())
        self.assertEqual(code, 1)
        self.assertIn("not ready", err)
        self.assertEqual(self.portfolio()["cash"], 1000)

    def test_another_orders_id_cannot_confirm_this_order(self):
        doc = small_orders("1")
        other = json.loads(json.dumps(doc["orders"][0]))
        other["qty"] = "2"
        doc["orders"].append(other)
        self.write_orders(doc)
        self.run_risk()
        id1, id2 = ticket.fingerprint(doc["orders"][0]), ticket.fingerprint(other)
        self.assertNotEqual(id1, id2)
        for reply in ("yes " + id2, "yes", "yes to all", "yes %s %s" % (id1, id2)):
            code, text, _ = self.tk("approve", "--index", "1", "--reply", reply)
            self.assertEqual(code, 1, reply)
            self.assertIn("Not recorded", text)
        self.assertFalse(os.path.exists(self.state))
        self.assertEqual(self.portfolio()["positions"], [])
        self.assertEqual(self.tk("approve", "--index", "1", "--reply", "yes " + id1)[0], 0)
        self.assertEqual(self.result()[0], 0)

    def test_a_declined_order_is_never_recorded(self):
        self.run_risk()
        self.assertEqual(self.tk("decline", "--index", "1", "--reply", "no")[0], 0)
        self.assertEqual(self.result()[0], 1)
        self.assertEqual(self.portfolio()["positions"], [])

    def test_with_the_yes_the_simulated_fill_is_recorded_once(self):
        self.assertEqual(self.run_risk()[0], 0)
        code, text, _ = self.tk("show", "--index", "1")
        self.assertIn("SIMULATED", text)
        self.assertIn("READY", text)
        self.assertNotIn("place_stock_order", text)
        self.assertEqual(self.tk("approve", "--index", "1", "--reply", self.conf())[0], 0)
        code, text, _ = self.result()
        self.assertEqual(code, 0, text)
        pf = self.portfolio()
        self.assertEqual((pf["cash"], pf["simulated"], pf["positions"][0]["ticker"], pf["positions"][0]["shares"]),
                         (635.8, True, "TSLA", 1))
        assert_clean_portfolio(self, pf, "portfolio after a simulated fill")
        self.assertEqual(self.result()[0], 1)                       # the same yes cannot fill twice
        self.assertEqual(self.portfolio()["cash"], 635.8)
        with open(self.state) as fh:
            st = json.load(fh)
        self.assertEqual([r["status"] for r in st["orders"]], ["approved", "placed", "filled"])
        self.assertEqual((st["orders"][0]["reply"], st["orders"][0]["confirmed_id"]),
                         (self.conf(), self.conf()[4:]))

    def test_a_fill_cannot_exceed_what_was_approved(self):
        self.run_risk()
        self.tk("approve", "--index", "1", "--reply", self.conf())
        code, _, err = self.tk("result", "--index", "1", "--status", "placed", "--filled-qty", "2",
                               "--filled-price", "364.20", "--portfolio", self.pf)
        self.assertEqual(code, 1)
        self.assertIn("bigger than the approved order", err)
        self.assertEqual(self.portfolio()["positions"], [])

    def test_the_original_8_share_order_is_too_big_for_1000_dollars(self):
        self.write_orders(small_orders("8"))                        # $2,900 of stock, $46.88 at risk
        code, text, _ = self.run_risk()
        self.assertEqual(code, 1)
        self.assertIn("BLOCK", text)
        self.assertEqual(self.tk("approve", "--index", "1", "--reply", self.conf())[0], 1)
        self.assertEqual(self.portfolio()["cash"], 1000)

    def test_exit_needs_its_own_yes_and_never_sells_more_than_held(self):
        self.run_risk()
        self.tk("approve", "--index", "1", "--reply", self.conf())
        self.result()
        late = "2026-10-19 15:55"
        code, _, _ = call(ticket.main, ["flatten", "--symbol", "TSLA", "--orders", self.orders,
                                        "--portfolio", self.pf, "--config", self.cfg, "--now", late])
        self.assertEqual(code, 0)
        code, _, err = call(ticket.main, ["flatten", "--symbol", "TSLA", "--qty", "2", "--orders", self.orders,
                                          "--portfolio", self.pf, "--config", self.cfg, "--now", late])
        self.assertEqual(code, 1)
        self.assertIn("short sale", err)
        call(check.main, ["--orders", self.orders, "--config", self.cfg, "--portfolio", self.pf,
                          "--prices", self.none, "--state", self.state, "--now", late, "--out", self.risk])
        args = ["--orders", self.orders, "--config", self.cfg, "--risk", self.risk, "--state", self.state,
                "--now", late]
        sell = ["result", "--index", "1", "--status", "placed", "--filled-qty", "1", "--filled-price", "366.10",
                "--portfolio", self.pf]
        self.assertEqual(call(ticket.main, sell + args)[0], 1)      # the sell has no yes yet
        self.assertEqual(self.portfolio()["positions"][0]["shares"], 1)
        self.assertEqual(call(ticket.main, ["approve", "--index", "1", "--reply", self.conf()] + args)[0], 0)
        self.assertEqual(call(ticket.main, sell + args)[0], 0)
        pf = self.portfolio()
        self.assertEqual((pf["positions"], pf["cash"]), ([], 1001.9))


if __name__ == "__main__":
    unittest.main()
