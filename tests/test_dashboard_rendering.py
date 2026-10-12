"""Report-level regression tests, with no model or notification calls."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.analyzer import AnalysisResult, GeminiAnalyzer
from src.notification import NotificationService


class DashboardRenderingTests(unittest.TestCase):
    def setUp(self):
        self.service = NotificationService.__new__(NotificationService)
        self.service._report_summary_only = False
        self.valid = AnalysisResult(code="600750", name="华润江中", sentiment_score=75,
                                    trend_prediction="看多", operation_advice="待验证候选", decision_type="hold")
        self.missing = AnalysisResult.unavailable("600351", "亚宝药业", "涨跌幅冲突", "insufficient_data")
        self.failed = AnalysisResult.unavailable("000028", "国药一致", "模型解析失败")

    def test_all_report_formats_account_for_failures(self):
        for method in (self.service.generate_dashboard_report, self.service.generate_daily_report,
                       self.service.generate_wechat_dashboard, self.service.generate_wechat_summary):
            with self.subTest(method=method.__name__):
                report = method([self.valid, self.missing, self.failed])
                self.assertIn("股票池：3只", report)
                self.assertIn("有效分析：1只", report)
                self.assertIn("数据不足：1只", report)
                self.assertIn("处理失败：1只", report)
                self.assertIn("600351：数据不足", report)
                self.assertNotIn("亚宝药业(600351)", report)

    def test_all_failed_report_contains_no_trade_plan(self):
        report = self.service.generate_dashboard_report([self.missing, self.failed])
        self.assertIn("有效分析：0只", report)
        self.assertNotIn("评分 50", report)
        self.assertNotIn("理想买入点", report)

    def test_single_failed_report_has_no_fake_price_or_score(self):
        report = self.service.generate_single_stock_report(self.missing)
        self.assertIn("涨跌幅冲突", report)
        self.assertNotIn("50", report)
        self.assertNotIn("0.0", report)

    def test_candidates_do_not_use_high_score_buy_fallback(self):
        self.valid.sentiment_score = 99
        self.assertEqual(self.service._get_signal_level(self.valid)[0], "待验证候选")
        self.assertEqual(self.valid.get_emoji(), "🟡")

    def test_snapshot_uses_provider_preclose(self):
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        snapshot = analyzer._build_market_snapshot({
            "today": {"close": 6.91, "pre_close": 7.07}, "yesterday": {"close": 6.82},
        })
        self.assertEqual(snapshot["prev_close"], "7.07")
        self.assertEqual(snapshot["change_amount"], "-0.16")

    def test_unstructured_model_response_is_not_a_market_signal(self):
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        output = analyzer._parse_response("强烈买入，85分", "600351", "亚宝药业")
        self.assertFalse(output.success)
        self.assertEqual(output.decision_type, "invalid")

    def test_bad_snapshot_is_rejected_before_any_model_call(self):
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer.is_available = Mock(return_value=True)
        analyzer._call_litellm = Mock()
        data = {"code": "600351", "stock_name": "亚宝药业", "today": {
            "close": 6.91, "pre_close": 6.82, "pct_chg": -2.26,
            "ma5": 6.864, "ma10": 6.834, "ma20": 6.776,
        }}
        with patch("src.analyzer.get_config", return_value=SimpleNamespace(gemini_request_delay=0)):
            output = analyzer.analyze(data)
        self.assertFalse(output.success)
        self.assertEqual(output.analysis_status, "insufficient_data")
        analyzer._call_litellm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
