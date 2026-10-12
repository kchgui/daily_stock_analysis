"""Deterministic input checks and evidence gates for dashboard generation."""

import math
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional


def parse_stock_list(value: str) -> List[str]:
    """Normalize separators, preserve leading zeroes, validate and deduplicate."""
    tokens = re.split(r"[,，;；、\s]+", value.strip())
    codes = []
    for token in tokens:
        code = token.strip().upper()
        if not code:
            continue
        if not re.fullmatch(
            r"(?:\d{5,6}(?:\.(?:SH|SZ|BJ|HK))?|(?:SH|SZ|BJ|HK)\d{5,6}|"
            r"\^?[A-Z][A-Z0-9]*(?:[.\-][A-Z0-9]+)?)", code
        ):
            raise ValueError(f"STOCK_LIST 包含无效代码：{code}；请仅填写股票代码")
        if code not in codes:
            codes.append(code)
    return codes


def number(value: Any) -> Optional[float]:
    """Reject missing, non-finite and boolean values without inventing zeroes."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def validate_context(context: Dict[str, Any]) -> List[str]:
    """Check one snapshot; never reconcile incompatible fields silently."""
    today = context.get("today") or {}
    trend = context.get("trend_analysis") or {}
    errors = []
    close = number(today.get("close"))
    if close is None or close <= 0:
        errors.append("缺少有效价格")
    for key in ("ma5", "ma10", "ma20"):
        value = number(trend.get(key, today.get(key)))
        if value is None or value <= 0:
            errors.append(f"缺少有效 {key.upper()}")
    prev = number(today.get("pre_close"))
    if prev is None:
        prev = number((context.get("yesterday") or {}).get("close"))
    pct = number(today.get("pct_chg"))
    if close is not None and prev is not None and prev > 0 and pct is not None:
        if abs((close / prev - 1) * 100 - pct) > 0.15:
            errors.append("价格、前收盘与涨跌幅口径不一致")
    high, low = number(today.get("high")), number(today.get("low"))
    if high is not None and low is not None and close is not None:
        if low <= 0 or high < low or not low - 0.01 <= close <= high + 0.01:
            errors.append("最高价、最低价与最新价不一致")
    volume, amount = number(today.get("volume")), number(today.get("amount"))
    if volume is not None and amount is not None and volume > 0 and amount > 0:
        if high is not None and low is not None and low > 0:
            average = amount / volume
            if average < low * 0.95 or average > high * 1.05:
                errors.append("成交量与成交额单位或截点不一致")
    return errors


def apply_evidence_gate(result: Any, context: Dict[str, Any], news_context: Optional[str]) -> None:
    """Keep model prose subordinate to verified numerical data and entry rules."""
    if not result.success:
        return
    trend = context.get("trend_analysis") or {}
    today = context.get("today") or {}
    ma = [number(trend.get(key, today.get(key))) for key in ("ma5", "ma10", "ma20")]
    price = number(today.get("close"))
    if price is None or any(value is None or value <= 0 for value in ma):
        return
    ma5, ma10, ma20 = ma
    bias = (price / ma5 - 1) * 100
    bullish = ma5 > ma10 > ma20
    gate_passed = bullish and price >= ma20 and -2 <= bias <= 5
    score = number(trend.get("signal_score"))
    if score is not None:
        result.sentiment_score = max(0, min(100, int(score)))
    dashboard = deepcopy(result.dashboard or {})
    data = dashboard.setdefault("data_perspective", {})
    data["trend_status"] = {
        "ma_alignment": f"MA5={ma5:.2f}，MA10={ma10:.2f}，MA20={ma20:.2f}",
        "is_bullish": bullish,
        "trend_score": trend.get("trend_strength", "未知"),
    }
    position = data.setdefault("price_position", {})
    position.update(current_price=price, ma5=ma5, ma10=ma10, ma20=ma20,
                    bias_ma5=round(bias, 2), bias_status="待确认" if not gate_passed else "规则范围内")
    chip = context.get("chip") or {}
    def chip_value(key):
        value = number(chip.get(key))
        return value if value is not None else "未知"

    data["chip_structure"] = {
        "profit_ratio": chip_value("profit_ratio"), "avg_cost": chip_value("avg_cost"),
        "concentration": chip_value("concentration_90"),
        "chip_health": "估计数据，需复核" if chip else "数据缺失",
    }
    realtime = context.get("realtime") or {}
    data["volume_analysis"] = {
        "volume_ratio": realtime.get("volume_ratio", "未知"),
        "turnover_rate": realtime.get("turnover_rate", "未知"),
        "volume_status": trend.get("volume_status", "未知"),
        "volume_meaning": "量比与历史日线量能为不同口径，不能据此证明主力洗盘。",
    }
    position["support_level"] = trend.get("support_level", "未知")
    position["resistance_level"] = trend.get("resistance_level", "未知")
    intel = dashboard.setdefault("intelligence", {})
    if not context.get("news_evidence_available", bool(news_context)):
        intel.update(latest_news="未获取有效新闻证据；不能据此确认无重大利空", earnings_outlook="未知",
                     sentiment_summary="未获取有效舆情证据", positive_catalysts=[])
        result.news_summary = intel["latest_news"]
        result.market_sentiment = "未知"
    plan = dashboard.setdefault("battle_plan", {})
    plan["action_checklist"] = [
        ("✅" if bullish else "❌") + " 均线多头排列（程序校验）",
        ("✅" if -2 <= bias <= 5 else "❌") + f" MA5乖离率：{bias:.2f}%（程序计算）",
        "⚠️ 量价现象不能证明主力身份或洗盘",
        "⚠️ 新闻和公告须逐项核验，未搜到不等于无利空",
        "⚠️ 筹码数据仅作估计，缺失时状态为未知",
        "⚠️ 估值需行业及历史对比，不能仅凭PE绝对值判定",
    ]
    plan["position_strategy"] = {
        "suggested_position": "未提供账户持仓和风险预算，不生成个人仓位比例",
        "entry_plan": "满足入场条件并核验公告后再制定计划",
        "risk_control": "根据账户风险预算、交易限制及实际成交价制定退出计划",
    }
    plan["sniper_points"] = {
        "ideal_buy": "待核验支撑及成交条件", "secondary_buy": "不自动生成补仓点",
        "stop_loss": "待制定可执行退出条件", "take_profit": "未验证收益空间，不生成目标价",
    }
    core = dashboard.setdefault("core_conclusion", {})
    is_buy = result.decision_type == "buy" or any(word in result.operation_advice for word in ("买入", "加仓"))
    if is_buy:
        result.confidence_level = "低"
        result.operation_advice = "待验证候选" if gate_passed else "观望"
        result.decision_type = "hold"
        result.analysis_summary = (
            "技术入场条件通过，需核验行情截点、公告及账户风险后制定计划。" if gate_passed
            else "未通过严格多头排列或乖离率条件，取消买入建议。"
        )
        result.buy_reason = result.analysis_summary
        core.update(one_sentence=result.analysis_summary, signal_type="🟡待验证候选" if gate_passed else "⚪观望",
                    time_sensitivity="条件成立后复核")
        plan["sniper_points"] = {
            "ideal_buy": "待核验支撑及成交条件", "secondary_buy": "不自动生成补仓点",
            "stop_loss": "待制定可执行退出条件", "take_profit": "未验证收益空间，不生成目标价",
        }
    core["position_advice"] = {
        "no_position": "候选信号不等于可执行买入；核验数据和公告后制定计划。",
        "has_position": "结合实际成本、权重及原持有逻辑复核，不按模型措辞直接调仓。",
    }
    if result.decision_type == "sell":
        result.operation_advice = "风险复核"
        core.update(one_sentence="趋势风险触发复核，结合原持有逻辑和可成交条件制定退出计划。",
                    time_sensitivity="及时复核")
        plan["sniper_points"] = {
            "ideal_buy": "未生成入场计划", "secondary_buy": "未生成补仓计划",
            "stop_loss": "结合实际成本和可成交条件复核", "take_profit": "未生成目标价",
        }
    dashboard["quality"] = {
        "score_label": "技术规则分（非胜率）" if score is not None else "模型评分（未经校准，非胜率）",
        "price_asof": str(context.get("date", "未知")),
        "unknowns": ["实时行情时间戳需核验", "账户仓位与风险预算未知"],
    }
    result.dashboard = dashboard
