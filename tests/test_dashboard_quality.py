"""Regression tests for real dashboard input and evidence failures."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.config import Config
from src.dashboard_quality import apply_evidence_gate, parse_stock_list, validate_context


def context():
    return {
        "date": "2026-10-12", "code": "600351",
        "today": {"close": 6.91, "pre_close": 6.82, "pct_chg": 1.32,
                  "high": 7.10, "low": 6.90, "volume": 23620000, "amount": 165000000,
                  "ma5": 6.864, "ma10": 6.834, "ma20": 6.776},
        "trend_analysis": {"signal_score": 75, "trend_strength": 75},
    }


def result():
    return SimpleNamespace(success=True, operation_advice="买入", decision_type="buy",
                           sentiment_score=85, dashboard={}, analysis_summary="买入", buy_reason="买入")


class StockListTests(unittest.TestCase):
    def test_reported_sixteen_codes_and_mixed_separators(self):
        text = ("601921，605266，603551，603111，002576，002441，000028，600750，"
                "002299，600007，600032，301370，688270，002922，603738，600522")
        self.assertEqual(len(parse_stock_list(text)), 16)
        self.assertEqual(parse_stock_list("000028；aapl\n00700,000028 BRK.B"), ["000028", "AAPL", "00700", "BRK.B"])

    def test_invalid_code_does_not_fall_back_to_demo_stocks(self):
        with self.assertRaises(ValueError):
            parse_stock_list("600351,1234567")
        with patch.dict(os.environ, {"STOCK_LIST": "股票600351"}):
            with self.assertRaises(ValueError):
                Config(stock_list=[]).refresh_stock_list()

    def test_refresh_uses_same_parser(self):
        with patch.dict(os.environ, {"STOCK_LIST": "000028，600750\n000028", "ENV_FILE": "missing-test.env"}):
            config = Config(stock_list=[])
            config.refresh_stock_list()
            self.assertEqual(config.stock_list, ["000028", "600750"])


class SnapshotTests(unittest.TestCase):
    def test_consistent_snapshot(self):
        self.assertEqual(validate_context(context()), [])

    def test_reported_price_conflict(self):
        data = context()
        data["today"]["pct_chg"] = -2.26
        self.assertTrue(any("涨跌幅" in issue for issue in validate_context(data)))

    def test_reported_lot_share_mismatch(self):
        data = context()
        data["today"]["volume"] = 236200
        self.assertTrue(any("单位" in issue for issue in validate_context(data)))

    def test_missing_and_nonfinite_are_not_zero(self):
        data = context()
        data["today"]["ma5"] = float("nan")
        self.assertTrue(any("MA5" in issue for issue in validate_context(data)))
        self.assertTrue(validate_context({"today": {}}))

    def test_actual_preclose_precedes_older_historical_close(self):
        data = context()
        data["yesterday"] = {"close": 5}
        self.assertEqual(validate_context(data), [])


class EvidenceTests(unittest.TestCase):
    def test_eligible_buy_becomes_candidate_not_probability(self):
        output = result()
        apply_evidence_gate(output, context(), None)
        self.assertEqual(output.operation_advice, "待验证候选")
        self.assertEqual(output.decision_type, "hold")
        self.assertEqual(output.sentiment_score, 75)
        self.assertEqual(output.dashboard["data_perspective"]["chip_structure"]["avg_cost"], "未知")
        self.assertIn("不能据此确认", output.dashboard["intelligence"]["latest_news"])
        self.assertNotRegex(output.dashboard["battle_plan"]["position_strategy"]["suggested_position"], r"\d.*成")

    def test_nonbullish_model_buy_is_blocked(self):
        data = context()
        data["today"]["ma10"] = 6.7
        output = result()
        apply_evidence_gate(output, data, None)
        self.assertEqual(output.operation_advice, "观望")
        self.assertFalse(output.dashboard["data_perspective"]["trend_status"]["is_bullish"])
        self.assertNotIn("买入", output.dashboard["core_conclusion"]["position_advice"]["has_position"])

    def test_excess_bias_blocks_model_buy(self):
        data = context()
        data["today"]["close"] = 8
        output = result()
        apply_evidence_gate(output, data, None)
        self.assertEqual(output.operation_advice, "观望")


if __name__ == "__main__":
    unittest.main()
