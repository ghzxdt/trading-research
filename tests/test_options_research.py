import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from options_research import (normalize, ingest, import_file, load, history, summarize, select_expression,
                              executable_pnl, debit_spread_pnl, price_scenarios,
                              evaluate_levels, level_study)

NOW = "2026-11-09T15:00:05+00:00"
SCRATCH = Path(__file__).resolve().parents[1] / "work" / "options_tests"


def contract(**changes):
    row = {"symbol": "SPY", "contract_id": "SPY-20261113-C-500", "expiry": "2026-11-13",
           "right": "C", "strike": 500, "multiplier": 100, "deliverable": "100 SPY shares",
           "timestamp": "2026-11-09T15:00:00+00:00", "available_at": "2026-11-09T15:00:01+00:00",
           "expiration_at": "2026-11-13T21:00:00+00:00", "source": "fixture-verified",
           "bid": 1., "ask": 1.05, "bid_size": 20, "ask_size": 20,
           "volume": 50, "open_interest": 100, "open_interest_as_of": "2026-11-06",
           "oi_available_at": "2026-11-09T13:00:00+00:00", "iv": .2, "delta": .5, "gamma": .02}
    row.update(changes)
    return row


def exit_contract(**changes):
    return contract(timestamp="2026-11-09T15:05:00+00:00", available_at="2026-11-09T15:05:01+00:00", **changes)


class OptionDataTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"APP_REPLAY": "0", "APP_OFFLINE": "0"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_import_is_idempotent_and_asof_preserves_old_observation(self):
        self.assertEqual(ingest(self.root, [contract()])["inserted"], 1)
        self.assertEqual(ingest(self.root, [contract()])["inserted"], 0)
        later = contract(timestamp="2026-11-09T15:10:00Z", available_at="2026-11-09T15:10:01Z", ask=1.2)
        ingest(self.root, [later])
        self.assertEqual(load(self.root, "SPY", NOW)[0]["ask"], 1.05)
        self.assertEqual(len(history(self.root, "SPY", "2026-11-09T16:00:00Z")), 2)
        self.assertEqual(load(self.root, "SPY", "2026-11-09T16:00:00Z")[0]["ask"], 1.2)

    def test_import_rejects_batch_before_any_write(self):
        bad = contract(multiplier=None)
        with self.assertRaises(ValueError):
            ingest(self.root, [contract(), bad])
        self.assertFalse((self.root / "data/options_research/events.jsonl").exists())

    def test_store_tampering_cannot_silently_change_history(self):
        ingest(self.root, [contract()])
        path = self.root / "data/options_research/events.jsonl"
        text = path.read_text().replace('"ask": 1.05', '"ask": 1.06')
        path.write_text(text)
        with self.assertRaisesRegex(ValueError, "hash chain"):
            load(self.root, "SPY", NOW)
        with self.assertRaisesRegex(ValueError, "hash chain"):
            ingest(self.root, [contract(ask=1.1)])
        self.assertEqual(path.read_text(), text)

    def test_replay_import_cannot_create_forward_data(self):
        with patch.dict(os.environ, {"APP_REPLAY": "1"}):
            with self.assertRaises(ValueError):
                ingest(self.root, [contract()])
        self.assertFalse((self.root / "data").exists())

    def test_json_import_uses_same_validation_and_receipt_provenance(self):
        path = self.root / "source.json"
        path.write_text(json.dumps({"records": [contract()]}))
        self.assertEqual(import_file(self.root, path)["inserted"], 1)
        event = json.loads((self.root / "data/options_research/events.jsonl").read_text())
        self.assertIn("ingested_at", event)

    def test_explicit_timezone_and_causal_availability_required(self):
        for changes in ({"timestamp": "2026-11-09T15:00:00"}, {"available_at": "2026-11-09T14:59:00Z"},
                        {"contract_id": ""}, {"multiplier": None}, {"adjusted": True, "deliverable": ""}):
            with self.assertRaises(ValueError):
                normalize(contract(**changes))

    def test_conflicting_same_timestamp_versions_cannot_depend_on_input_order(self):
        rows = [contract(), contract(ask=1.1)]
        for ordered in (rows, list(reversed(rows))):
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                summarize(ordered, 500, NOW)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            ingest(self.root, rows)
        self.assertFalse((self.root / "data/options_research/events.jsonl").exists())

    def test_invalid_adjustment_flag_and_fractional_contract_counts_are_rejected(self):
        for row in (contract(adjusted="maybe"), contract(open_interest=1.5), contract(volume=.25)):
            with self.assertRaises(ValueError):
                normalize(row)

    def test_missing_oi_time_does_not_invent_a_wall(self):
        row = contract(oi_available_at=None)
        report = summarize([row], 500, NOW)
        self.assertEqual(report["contracts"], 1)
        self.assertEqual(report["levels"], [])
        self.assertEqual(report["dealer_positioning"], "unknown")

    def test_future_oi_is_not_yet_available(self):
        report = summarize([contract(oi_available_at="2026-11-09T16:00:00Z")], 500, NOW)
        self.assertEqual(report["levels"], [])

    def test_repeated_snapshots_do_not_double_count_oi(self):
        row = contract()
        report = summarize([row, row], 500, NOW)
        self.assertEqual(report["contracts"], 1)
        self.assertEqual(report["expiries"][0]["call_open_interest"], 100)
        level = report["levels"][0]
        self.assertEqual(level["behavior"], "unvalidated")
        self.assertEqual(level["unsigned_dollar_gamma_per_one_percent"], 500000)
        self.assertEqual(level["dealer_gamma_scenarios"]["assume_all_short"], -500000)

    def test_summary_exposes_quote_age_and_never_sums_different_markets(self):
        result = summarize([contract()], 500, "2026-11-09T16:00:00Z")
        self.assertEqual(result["quote_health"]["execution_qualified_contracts"], 0)
        self.assertEqual(result["quote_health"]["latest_quote_age_seconds"], 3600)
        with self.assertRaises(ValueError):
            summarize([contract(), contract(symbol="QQQ", contract_id="QQQ-C")], 500, NOW)


class OptionExecutionTests(unittest.TestCase):
    def account(self, **changes):
        result = {"max_trade_debit": 200, "max_loss_per_trade": 200, "available_cash": 1000,
                  "options_permitted": True, "fee_per_contract_per_side": .65}
        result.update(changes)
        return result

    def test_unknown_risk_budget_remains_a_comparison_not_recommended_sizing(self):
        result = select_expression([contract()], "long", as_of=NOW)
        self.assertEqual(result["status"], "candidate")
        self.assertFalse(result["sizing_allowed"])
        self.assertIsNone(result["quantity"])

    def test_delta_selection_does_not_move_farther_otm_to_force_budget(self):
        costly = contract(bid=1.95, ask=2, delta=.5)
        cheap = contract(contract_id="SPY-20261113-C-510", strike=510, bid=.45, ask=.5, delta=.1)
        result = select_expression([costly, cheap], "long", self.account(max_trade_debit=100), NOW)
        self.assertEqual(result["status"], "no_feasible_expression")
        self.assertEqual(result["contract"]["strike"], 500)

    def test_quote_account_feasibility_does_not_certify_strategy(self):
        result = select_expression([contract()], "long", self.account(), NOW)
        self.assertEqual(result["status"], "eligible")
        self.assertFalse(result["sizing_allowed"])
        self.assertFalse(result["strategy_validated"])

    def test_selection_cannot_choose_a_different_underlying_silently(self):
        with self.assertRaises(ValueError):
            select_expression([contract(), contract(symbol="QQQ", contract_id="QQQ-C")], "long", as_of=NOW)

    def test_unknown_fees_cannot_certify_after_cost_feasibility(self):
        account = self.account()
        account.pop("fee_per_contract_per_side")
        self.assertEqual(select_expression([contract()], "long", account, NOW)["status"], "candidate")

    def test_loss_and_cash_limits_reserve_the_closing_fee(self):
        result = select_expression([contract()], "long", self.account(max_loss_per_trade=106), NOW)
        self.assertEqual(result["status"], "no_feasible_expression")
        self.assertAlmostEqual(result["debit"], 105.65)
        self.assertAlmostEqual(result["max_loss"], 106.3)

    def test_stale_crossed_unknown_size_and_unverified_timestamp_quotes_are_blocked(self):
        for row in (contract(timestamp="2026-11-09T14:00:00Z"), contract(bid=2), contract(ask_size=None),
                    contract(quality=["timestamp_unverified"])):
            self.assertEqual(select_expression([row], "long", self.account(), NOW)["status"], "unavailable")

    def test_same_day_requires_explicit_expiration_cutoff(self):
        row = contract(expiry="2026-11-09", expiration_at=None)
        account = self.account(min_dte=0)
        self.assertEqual(select_expression([row], "long", account, NOW)["status"], "unavailable")

    def test_put_direction_requires_negative_delta(self):
        row = contract(right="P", contract_id="SPY-P", delta=-.5)
        self.assertEqual(select_expression([row], "short", self.account(), NOW)["instrument"], "long_put")

    def test_pnl_uses_entry_ask_exit_bid_and_actual_multiplier(self):
        result = executable_pnl(contract(), exit_contract(bid=1.2, ask=1.25), fees=.65)
        self.assertAlmostEqual(result["net_pnl"], 13.7)
        self.assertEqual(result["extra_theta_deduction"], 0)
        result = executable_pnl(contract(multiplier=10), exit_contract(multiplier=10, bid=1.2, ask=1.25), fees=.65)
        self.assertAlmostEqual(result["net_pnl"], .2)

    def test_unfilled_quantity_and_wrong_contract_cannot_generate_pnl(self):
        for closing, quantity in ((exit_contract(bid_size=0), 1), (exit_contract(contract_id="OTHER"), 1),
                                  (exit_contract(), 1.5)):
            with self.assertRaises(ValueError):
                executable_pnl(contract(), closing, quantity)

    def test_exit_cannot_precede_entry_information(self):
        entry = contract(available_at="2026-11-09T15:00:50Z")
        closing = contract(timestamp="2026-11-09T15:00:30Z", available_at="2026-11-09T15:00:51Z")
        with self.assertRaises(ValueError):
            executable_pnl(entry, closing)

    def test_vertical_uses_four_fees_and_rejects_unsynchronized_legs(self):
        long_entry = contract(bid=2.9, ask=3)
        short_entry = contract(contract_id="SPY-C505", strike=505, bid=1, ask=1.1)
        long_exit = exit_contract(bid=4, ask=4.1)
        short_exit = exit_contract(contract_id="SPY-C505", strike=505, bid=1, ask=1.1)
        result = debit_spread_pnl(long_entry, short_entry, long_exit, short_exit, fees=.65)
        self.assertAlmostEqual(result["net_pnl"], 87.4)
        self.assertAlmostEqual(result["fees"], 2.6)
        short_exit["timestamp"] = "2026-11-09T15:05:03Z"
        short_exit["available_at"] = "2026-11-09T15:05:04Z"
        with self.assertRaises(ValueError):
            debit_spread_pnl(long_entry, short_entry, long_exit, short_exit)

    def test_joint_theoretical_scenarios_are_explicitly_unvalidated(self):
        result = price_scenarios(contract(), 500, [
            {"label": "up", "spot_change_pct": .01, "iv_change": -.02, "elapsed_minutes": 20},
            {"label": "down", "spot_change_pct": -.01, "iv_change": .02, "elapsed_minutes": 20}], NOW)
        self.assertEqual(result["status"], "theoretical_only")
        self.assertGreater(result["scenarios"][0]["theoretical_premium"], result["scenarios"][1]["theoretical_premium"])
        self.assertIsNone(result["scenarios"][0]["probability"])

    def test_scenarios_cannot_substitute_future_spot_for_expired_settlement(self):
        row = contract()
        after = price_scenarios(row, 500, [{"spot_change_pct": .01}], "2026-11-13T22:00:00Z")
        self.assertEqual(after["status"], "unavailable")
        with self.assertRaisesRegex(ValueError, "post-expiration"):
            price_scenarios(row, 500, [{"spot_change_pct": .01, "elapsed_minutes": 10000}], NOW)

    def test_spread_exit_cannot_precede_complete_entry_information(self):
        long_entry = contract(bid=2.9, ask=3)
        short_entry = contract(contract_id="SPY-C505", strike=505, bid=1, ask=1.1,
                               available_at="2026-11-09T15:00:02Z")
        long_exit = contract(bid=3.1, ask=3.2, timestamp="2026-11-09T15:00:01Z", available_at="2026-11-09T15:00:02Z")
        short_exit = contract(contract_id="SPY-C505", strike=505, bid=1, ask=1.1,
                             timestamp="2026-11-09T15:00:02Z", available_at="2026-11-09T15:00:03Z")
        with self.assertRaisesRegex(ValueError, "complete entry"):
            debit_spread_pnl(long_entry, short_entry, long_exit, short_exit)


class FrozenLevelTests(unittest.TestCase):
    def bars(self):
        start = datetime(2026, 11, 9, 15, tzinfo=timezone.utc)
        values = [(99.8, 99.85, 99.7, 99.8), (99.9, 100.02, 99.85, 100),
                  (100, 100.03, 99.85, 99.9), (99.9, 99.95, 99.8, 99.9)]
        return [{"timestamp": (start + timedelta(minutes=i)).isoformat(),
                 "available_at": (start + timedelta(minutes=i + 1)).isoformat(),
                 "open": v[0], "high": v[1], "low": v[2], "close": v[3]} for i, v in enumerate(values)]

    def level(self, **changes):
        row = {"id": "OI-100", "price": 100, "knowledge_time": "2026-11-09T14:59:00Z", "source": "fixture"}
        row.update(changes)
        return row

    def test_only_pre_touch_levels_and_first_touch_count(self):
        result = evaluate_levels([self.level()], self.bars(), {"horizon_minutes": 2}, "2026-11-09T16:00:00Z")
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["observations"][0]["outcome"], "rejection")
        self.assertTrue(result["observations"][0]["touch_bar_unscored"])
        late = evaluate_levels([self.level(knowledge_time="2026-11-09T15:04:00Z")], self.bars(), as_of="2026-11-09T16:00:00Z")
        self.assertEqual(late["observations"], [])

    def test_both_outcomes_in_one_bar_are_not_ordered_from_ohlc(self):
        bars = self.bars()
        bars[2]["high"] = 100.2
        result = evaluate_levels([self.level()], bars, {"horizon_minutes": 2}, "2026-11-09T16:00:00Z")
        self.assertEqual(result["observations"][0]["outcome"], "ambiguous_unscored")

    def test_unknown_future_is_censored(self):
        result = evaluate_levels([self.level()], self.bars()[:2], {"horizon_minutes": 2}, "2026-11-09T15:02:00Z")
        self.assertEqual(result["observations"][0]["outcome"], "censored")

    def test_controls_require_explicit_links_and_never_certify_edge(self):
        result = level_study([self.level()], [self.level(id="control", matched_to="OI-100")], self.bars(),
                             {"horizon_minutes": 2}, "2026-11-09T16:00:00Z")
        self.assertTrue(result["explicit_control_links_present"])
        self.assertEqual(result["paired_sessions"], 1)
        self.assertIsNone(result["paired_session_bootstrap_95_interval"])
        self.assertFalse(result["validated_edge"])

    def test_later_contract_snapshot_invalidates_old_level_before_touch(self):
        old = self.level(contract_ids=["SPY-C100"], source_market="SPY", method_version="oi-v1")
        new = self.level(id="OI-100-new", contract_ids=["SPY-C100"], source_market="SPY", method_version="oi-v1",
                         knowledge_time="2026-11-09T15:00:30Z")
        result = evaluate_levels([old, new], self.bars(), {"horizon_minutes": 2}, "2026-11-09T16:00:00Z")
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["observations"][0]["level_id"], "OI-100-new")

    def test_cross_market_price_level_cannot_be_implicitly_rescaled(self):
        bars = [{**row, "symbol": "TQQQ"} for row in self.bars()]
        with self.assertRaises(ValueError):
            evaluate_levels([self.level(source_market="QQQ")], bars, as_of="2026-11-09T16:00:00Z")


if __name__ == "__main__":
    unittest.main()
