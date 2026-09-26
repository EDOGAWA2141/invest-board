#!/usr/bin/env python3
"""指标计算：10 年百分位、同比、趋势、信号标签。"""
from datetime import date, timedelta


def percentile(history, current, years=10, min_points=30):
    """计算当前值在历史窗口中的百分位。

    history: [(date_str, value)] 按日期升序。
    返回 (pct 或 None, 口径说明)。
    """
    if not history or len(history) < 2:
        return None, "数据不足"
    last_d = date.fromisoformat(history[-1][0])
    cutoff = (last_d - timedelta(days=365 * years)).isoformat()
    window = [v for d, v in history if d >= cutoff]
    basis = f"近{years}年"
    if len(window) < min_points:
        window = [v for _, v in history]
        basis = f"全部历史（{len(window)} 个观测点）"
        if len(window) < 12:
            return None, "数据不足"
    below = sum(1 for v in window if v <= current)
    return round(below / len(window) * 100, 1), basis


def yoy_monthly(history):
    """月度指数序列的同比增速（%）。返回 (yoy_pct, base_date)。"""
    if len(history) < 13:
        return None, None
    d_last = date.fromisoformat(history[-1][0])
    v_last = history[-1][1]
    # 目标：12 个月前的同一月份
    y, m = d_last.year, d_last.month
    m -= 12
    while m <= 0:
        m += 12
        y -= 1
    target_ym = f"{y}-{m:02d}"
    base = None
    for d, v in reversed(history[:-1]):
        if d[:7] == target_ym:
            base = (d, v)
            break
        if d[:7] < target_ym:
            base = (d, v)
            break
    if base is None or base[1] == 0:
        return None, None
    return round((v_last / base[1] - 1) * 100, 2), base[0]


def change_vs_prev(history):
    """返回 (prev_date, prev_value, 变动值, 变动 bp/%)。"""
    if len(history) < 2:
        return None
    (d0, v0), (d1, v1) = history[-2], history[-1]
    return {"date": d0, "value": v0, "delta": round(v1 - v0, 4)}


def pct_change_3m(history):
    """近 3 个月（~63 个交易日 / 3 个月度点）的百分比变化。"""
    if len(history) < 2:
        return None
    d_last = date.fromisoformat(history[-1][0])
    cutoff = (d_last - timedelta(days=95)).isoformat()
    base = next(((d, v) for d, v in history if d >= cutoff), history[0])
    v0, v1 = base[1], history[-1][1]
    if v0 == 0:
        return None
    return {"base_date": base[0], "pct": round((v1 / v0 - 1) * 100, 2)}


# ---- 信号标签 ----
def signal_leverage(pct):
    """居民杠杆（债务/GDP）：分位越高负担越重。"""
    if pct is None:
        return {"label": "暂无分位数据", "tone": "neutral"}
    if pct >= 80:
        return {"label": f"居民杠杆处于十年高位（{pct}% 分位），偿债负担偏重", "tone": "danger"}
    if pct <= 20:
        return {"label": f"居民杠杆处于十年低位（{pct}% 分位）", "tone": "ok"}
    return {"label": f"居民杠杆处于十年中位附近（{pct}% 分位）", "tone": "neutral"}


def signal_growth(pct):
    """收入增速：分位越低越弱。"""
    if pct is None:
        return {"label": "暂无分位数据", "tone": "neutral"}
    if pct <= 20:
        return {"label": f"收入增速处于十年低位（{pct}% 分位），增长动能偏弱", "tone": "warn"}
    if pct >= 80:
        return {"label": f"收入增速处于十年高位（{pct}% 分位）", "tone": "ok"}
    return {"label": f"收入增速处于十年中位附近（{pct}% 分位）", "tone": "neutral"}


def signal_house_price(pct):
    """房价同比涨幅分位：描述性为主，判断留给用户。"""
    if pct is None:
        return {"label": "暂无分位数据", "tone": "neutral"}
    if pct >= 80:
        return {"label": f"房价涨幅处于十年高位（{pct}% 分位）", "tone": "warn"}
    if pct <= 20:
        return {"label": f"房价涨幅处于十年低位（{pct}% 分位）", "tone": "info"}
    return {"label": f"房价涨幅处于十年中位附近（{pct}% 分位）", "tone": "neutral"}


def signal_pe(pct):
    if pct is None:
        return {"label": "历史数据积累中", "tone": "neutral"}
    if pct >= 80:
        return {"label": f"估值处于十年高位（{pct}% 分位），偏贵", "tone": "danger"}
    if pct <= 20:
        return {"label": f"估值处于十年低位（{pct}% 分位），相对便宜", "tone": "ok"}
    return {"label": f"估值处于十年中位附近（{pct}% 分位）", "tone": "neutral"}


def signal_yield(pct):
    if pct is None:
        return {"label": "历史数据积累中", "tone": "neutral"}
    if pct >= 80:
        return {"label": f"收益率处于十年高位（{pct}% 分位）→ 债券相对便宜", "tone": "ok"}
    if pct <= 20:
        return {"label": f"收益率处于十年低位（{pct}% 分位）→ 债券相对偏贵", "tone": "danger"}
    return {"label": f"收益率处于十年中位附近（{pct}% 分位）", "tone": "neutral"}


def signal_inflation(yoy):
    if yoy is None:
        return {"label": "待更新", "tone": "neutral"}
    if yoy >= 3.0:
        return {"label": f"同比 {yoy}%：明显高于美联储 2% 目标", "tone": "warn"}
    if yoy >= 2.0:
        return {"label": f"同比 {yoy}%：略高于 2% 目标", "tone": "neutral"}
    return {"label": f"同比 {yoy}%：低于 2% 目标", "tone": "info"}
