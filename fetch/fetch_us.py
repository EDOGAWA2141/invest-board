#!/usr/bin/env python3
"""美国指标抓取：全部使用免费公开数据源，无需 API key。

数据源（2026-09-26 实测可用）：
- FRED 无 key CSV：DGS10 / CPIAUCSL / PCEPI / WALCL / RRPONTSYD / WRESBAL / DFF / M2SL
- worldperatio.com/index/nasdaq-100/ ：Nasdaq-100 trailing PE（月度，≥10 年历史，HTML 内嵌 JS 数组）
- siblisresearch.com/data/nasdaq-100-pe-ratio/ ：Nasdaq-100 forward PE 当前值（月度更新）
- Robinhood fundamentals API：QQQ / SOXX / SMH trailing P/E（日度快照，免 key JSON）
  Zacks quote-feed 为备用源
"""
import csv
import io
import re
from datetime import datetime, timezone

import requests

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}
TIMEOUT = 60
COSD = "2016-01-01"  # 统一拉取 10 年窗口

FRED_SERIES = [
    "DGS10", "CPIAUCSL", "PCEPI", "WALCL",
    "RRPONTSYD", "WRESBAL", "DFF", "M2SL",
]


def fetch_fred_csv(series_id):
    """FRED 无 key CSV，返回 [(date_str, value)] 按日期升序。"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={COSD}"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    rows = []
    for row in csv.DictReader(io.StringIO(r.text)):
        d = (row.get("observation_date") or "").strip()
        v = (row.get(series_id) or "").strip()
        if not d or v in ("", "."):
            continue
        try:
            rows.append((d, float(v)))
        except ValueError:
            continue
    rows.sort(key=lambda x: x[0])
    if not rows:
        raise RuntimeError(f"FRED {series_id} 返回空数据")
    return rows


def _parse_js_data_array(html, var_name):
    """从 HTML 中提取 `var <var_name> = [...];` 的 [x, y] 数对。

    支持两种 x 格式：毫秒/秒时间戳、"YYYY-MM-DD" 字符串、
    Date.UTC(y, m, d)（注意 m 为 0 起始）。
    """
    m = re.search(var_name + r"\s*=\s*(\[(?:\[[^\]]*\],?\s*)*\])", html)
    if not m:
        raise RuntimeError(f"未找到 {var_name}")
    raw = m.group(1)
    hist = []
    # 格式 A：[Date.UTC(1990, 4, 1), 24.2719]
    for y, mo, d, val in re.findall(
            r"\[Date\.UTC\((\d+),\s*(\d+),\s*(\d+)\),\s*([\d.]+)\]", raw):
        hist.append((f"{int(y):04d}-{int(mo) + 1:02d}-{int(d):02d}", float(val)))
    # 格式 B：[1696118400000, 30.25] 或 ["2023-10-01", 30.25]
    for x, val in re.findall(r"\[\s*\"?([\d\-\.]+)\"?\s*,\s*([\d.]+)\s*\]", raw):
        if x.replace(".", "", 1).isdigit() and float(x) > 1e12:
            d = datetime.fromtimestamp(float(x) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        elif x.replace(".", "", 1).isdigit() and float(x) > 1e9:
            d = datetime.fromtimestamp(float(x), tz=timezone.utc).strftime("%Y-%m-%d")
        else:
            d = x[:10]
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            continue
        hist.append((d, float(val)))
    hist = sorted(set(hist), key=lambda t: t[0])
    return hist


def fetch_worldperatio_nasdaq_pe():
    """Nasdaq-100 trailing PE：月度历史（≥10 年）+ 当前值。"""
    url = "https://worldperatio.com/index/nasdaq-100/"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    for var in ("detailPE_data", "pe_data", "chart_data"):
        try:
            hist = _parse_js_data_array(r.text, var)
            if len(hist) >= 60:
                return hist
        except RuntimeError:
            continue
    raise RuntimeError("worldperatio 未找到可用的 PE 历史数组")


def fetch_siblis_nasdaq():
    """Siblis Research Nasdaq-100：返回 dict(trailing, forward, cape, asof)。

    解析页面主表 NASDAQ 100 行：Trailing P/E / Forward P/E / CAPE。
    asof 取 JSON-LD 中的 dateModified。
    """
    url = "https://siblisresearch.com/data/nasdaq-100-pe-ratio/"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    html = r.text

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    trailing = forward = cape = None
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in cells]
        cells = [c for c in cells if c]
        if len(cells) >= 5 and cells[0] == "NASDAQ 100":
            try:
                trailing = float(cells[1])
                forward = float(cells[2])
                cape = float(cells[4])
            except ValueError:
                pass
            break
    if trailing is None or forward is None:
        raise RuntimeError("Siblis 页面未解析到 NASDAQ 100 的 trailing/forward PE")

    asof = None
    m = re.search(r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})"', html)
    if m:
        asof = m.group(1)
    return {"trailing": trailing, "forward": forward, "cape": cape, "asof": asof}


def fetch_robinhood_pe(symbols=("QQQ", "SOXX", "SMH")):
    """Robinhood fundamentals：日度 trailing P/E 快照，免 key。

    返回 {symbol: (pe_float, market_date_str)}，market_date 为交易所日期。
    results 与请求 symbols 顺序对应。
    """
    url = "https://api.robinhood.com/fundamentals/?symbols=" + ",".join(symbols)
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    results = r.json().get("results", [])
    out = {}
    for sym, item in zip(symbols, results):
        pe = item.get("pe_ratio")
        if pe is None:
            continue
        out[sym] = (float(pe), item.get("market_date"))
    if "QQQ" not in out or "SOXX" not in out:
        raise RuntimeError("Robinhood 未返回 QQQ/SOXX 的 pe_ratio")
    return out


def fetch_zacks_pe(symbol):
    """Zacks quote-feed：备用日度 trailing P/E。返回 (pe_float, date_str)。"""
    url = f"https://quote-feed.zacks.com/index?t={symbol}"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()[symbol]["source"]["sungard"]
    pe = float(d["pe_ratio"])
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", d.get("last_trade_datetime", ""))
    date = f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None
    return pe, date


def fetch_daily_pe():
    """日度 trailing P/E：Robinhood 主，Zacks 备。

    返回 {symbol: {"pe": float, "date": str, "src": str}}。
    主备口径不同，调用方须按实际 src 标注来源。
    """
    out = {}
    try:
        for sym, (pe, date) in fetch_robinhood_pe().items():
            out[sym] = {"pe": pe, "date": date, "src": "Robinhood"}
    except Exception:
        pass
    for sym in ("QQQ", "SOXX"):
        if sym not in out:
            try:
                pe, date = fetch_zacks_pe(sym)
                out[sym] = {"pe": pe, "date": date, "src": "Zacks（备用口径）"}
            except Exception:
                pass
    if "QQQ" not in out or "SOXX" not in out:
        raise RuntimeError("日度 PE 主备源均失败")
    return out


def fetch_all_us():
    """抓取全部美国原始序列，返回 dict(series_id -> [(date, value)]) 及估值类快照。

    单个来源失败时只记录错误、继续抓其余来源（调用方对缺失序列做 STALE 兜底）。
    """
    import traceback
    out = {}
    for sid in FRED_SERIES:
        try:
            out[sid] = fetch_fred_csv(sid)
        except Exception:
            print(f"抓取失败 FRED {sid}", flush=True)
            traceback.print_exc()
    for name, fn in [
        ("NDX_PE_TRAILING_HIST", fetch_worldperatio_nasdaq_pe),
        ("NDX_SIBLIS", fetch_siblis_nasdaq),
        ("DAILY_PE", fetch_daily_pe),
    ]:
        try:
            out[name] = fn()
        except Exception:
            print(f"抓取失败 {name}", flush=True)
            traceback.print_exc()
    return out


if __name__ == "__main__":
    data = fetch_all_us()
    for k, v in data.items():
        if isinstance(v, list):
            print(f"{k}: {len(v)} 点, 最新 {v[-1]}")
        else:
            print(f"{k}: {v}")
