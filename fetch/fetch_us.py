#!/usr/bin/env python3
"""美国指标抓取：全部使用免费公开数据源。

数据源（2026-09-26 实测可用）：
- FRED：DGS10 / CPIAUCSL / PCEPI / WALCL / RRPONTSYD / WRESBAL / DFF / M2SL
  / BOGZ1FU103164103Q（Z.1 非金融企业股票净发行，季度 NSA）
  优先走官方 API（api.stlouisfed.org，需 FRED_API_KEY 环境变量），失败回退无 key CSV
- worldperatio.com/index/nasdaq-100/ ：Nasdaq-100 trailing PE（月度，≥10 年历史，HTML 内嵌 JS 数组）
- worldperatio.com/index/sp-500/ ：S&P 500 trailing PE（月度，≥10 年历史，同上）
- siblisresearch.com/data/nasdaq-100-pe-ratio/ ：Nasdaq-100 forward PE 当前值（月度更新）
- siblisresearch.com/data/sector-pe-earnings/ ：S&P 500 信息技术板块 forward PE 当前值（月度更新）
- production.dataviz.cnn.io/index/fearandgreed/graphdata ：CNN 恐惧贪婪指数（日度，免 key JSON，需浏览器 UA）
- Robinhood fundamentals API：QQQ / SOXX / SMH trailing P/E（日度快照，免 key JSON）
  Zacks quote-feed 为备用源
- renaissancecapital.com/IPO-Center/Stats ：Renaissance Capital 当年 YTD 已定价 IPO 家数/融资额/同比（日度更新）
"""
import csv
import io
import os
import re
from datetime import datetime, timedelta, timezone

import requests

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}
TIMEOUT = 60
# 抓取起始日期：动态 = 今天倒退 11 年（百分位窗口为 10 年，留 1 年缓冲），
# 每年随 workflow 运行日期自动后移，不写死。
COSD = (datetime.now(timezone.utc).date() - timedelta(days=365 * 11)).isoformat()

FRED_SERIES = [
    "DGS10", "CPIAUCSL", "PCEPI", "WALCL",
    "RRPONTSYD", "WRESBAL", "DFF", "M2SL",
    "BOGZ1FU103164103Q",
]
# BOGZ1FU103164103Q：Nonfinancial Corporate Business; Corporate Equities;
# Liability, Transactions（美联储 Z.1，季度 NSA，百万美元）。
# 含义=非金融企业股票净发行（新股发行 − 回购 − 现金并购注销等），负值=净回购。
# 注意：NSA 为真实季度流量（非年化）；季度 SA 版本（FA 系列）为年化值，不可直接求和。


def fetch_fred_api(series_id):
    """FRED 官方 API（api.stlouisfed.org，需 FRED_API_KEY 环境变量）。"""
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未设置 FRED_API_KEY")
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={key}&file_type=json"
           f"&observation_start={COSD}&sort_order=asc")
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    rows = []
    for o in r.json().get("observations", []):
        d = (o.get("date") or "").strip()
        v = (o.get("value") or "").strip()
        if not d or v in ("", "."):
            continue
        try:
            rows.append((d, float(v)))
        except ValueError:
            continue
    rows.sort(key=lambda x: x[0])
    if not rows:
        raise RuntimeError(f"FRED API {series_id} 返回空数据")
    return rows


def fetch_fred(series_id):
    """FRED：官方 API 优先（需 key），失败回退无 key CSV。"""
    try:
        return fetch_fred_api(series_id)
    except Exception as e:
        print(f"FRED API 失败 {series_id}（{e}），回退 CSV", flush=True)
    return fetch_fred_csv(series_id)


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


def fetch_worldperatio_sp500_pe():
    """S&P 500 trailing PE：月度历史（≥10 年，worldperatio HTML 内嵌 JS 数组）。"""
    url = "https://www.worldperatio.com/index/sp-500/"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    for var in ("detailPE_data", "pe_data", "chart_data"):
        try:
            hist = _parse_js_data_array(r.text, var)
            if len(hist) >= 60:
                return hist
        except RuntimeError:
            continue
    raise RuntimeError("worldperatio 未找到 S&P 500 的 PE 历史数组")


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


def fetch_siblis_it_sector():
    """Siblis Research S&P 500 信息技术板块：返回 dict(trailing, forward, asof)。

    解析 sector-pe-earnings 页面的估值表（表头含 Trailing P/E / Forward P/E）
    中 Information Technology 行；asof 取 JSON-LD 中的 dateModified。
    """
    url = "https://siblisresearch.com/data/sector-pe-earnings/"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    html = r.text
    trailing = forward = None
    for tbl in re.findall(r"<table[^>]*>(.*?)</table>", html, re.S):
        if "Trailing P/E" not in tbl or "Forward P/E" not in tbl:
            continue
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in cells]
            cells = [c for c in cells if c]
            if len(cells) >= 3 and cells[0] == "Information Technology":
                try:
                    trailing = float(cells[1])
                    forward = float(cells[2])
                except ValueError:
                    pass
                break
        if forward is not None:
            break
    if trailing is None or forward is None:
        raise RuntimeError("Siblis 板块页面未解析到 Information Technology 的 trailing/forward PE")

    asof = None
    m = re.search(r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})"', html)
    if m:
        asof = m.group(1)
    return {"trailing": trailing, "forward": forward, "asof": asof}


def fetch_cnn_fear_greed():
    """CNN 恐惧贪婪指数：当前值 + 约 1 年日度历史 + 9 个子指标。

    https://production.dataviz.cnn.io/index/fearandgreed/graphdata（免 key JSON，
    需浏览器 UA 否则 418）。返回 dict(score, rating, asof, history, subs)。
    """
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    fg = d["fear_and_greed"]
    hist = []
    for p in d.get("fear_and_greed_historical", {}).get("data", []):
        try:
            day = datetime.fromtimestamp(p["x"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            hist.append((day, float(p["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    hist = sorted(set(hist), key=lambda t: t[0])
    subs = {}
    for k, v in d.items():
        if k in ("fear_and_greed", "fear_and_greed_historical"):
            continue
        if isinstance(v, dict) and "rating" in v and "score" in v:
            try:
                subs[k] = {"rating": v["rating"], "score": round(float(v["score"]), 1)}
            except (TypeError, ValueError):
                continue
    if not hist or "score" not in fg:
        raise RuntimeError("CNN Fear & Greed 未解析到有效数据")
    return {"score": round(float(fg["score"]), 1), "rating": fg.get("rating", ""),
            "asof": (fg.get("timestamp") or "")[:10],
            "history": hist, "subs": subs}


def fetch_robinhood_pe(symbols=("QQQ", "SOXX", "SMH")):
    """Robinhood fundamentals：日度 trailing P/E 快照 + 52 周高低，免 key。

    返回 {symbol: {"pe": float, "date": str, "high_52w": float|None,
                   "high_52w_date": str|None, "low_52w": float|None,
                   "low_52w_date": str|None}}，date 为交易所日期。
    results 与请求 symbols 顺序对应。
    """
    url = "https://api.robinhood.com/fundamentals/?symbols=" + ",".join(symbols)
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    results = r.json().get("results", [])

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out = {}
    for sym, item in zip(symbols, results):
        pe = item.get("pe_ratio")
        if pe is None:
            continue
        out[sym] = {"pe": float(pe), "date": item.get("market_date"),
                    "high_52w": _f(item.get("high_52_weeks")),
                    "high_52w_date": item.get("high_52_weeks_date"),
                    "low_52w": _f(item.get("low_52_weeks")),
                    "low_52w_date": item.get("low_52_weeks_date")}
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

    返回 {symbol: {"pe": float, "date": str, "src": str,
                   "high_52w"...（仅 Robinhood 有 52 周高低）}}。
    主备口径不同，调用方须按实际 src 标注来源。
    """
    out = {}
    try:
        for sym, info in fetch_robinhood_pe().items():
            out[sym] = {"pe": info["pe"], "date": info["date"], "src": "Robinhood",
                        "high_52w": info["high_52w"],
                        "high_52w_date": info["high_52w_date"],
                        "low_52w": info["low_52w"],
                        "low_52w_date": info["low_52w_date"]}
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


# ---------------- Renaissance Capital 当年 IPO ----------------
def fetch_renaissance_ytd():
    """Renaissance Capital IPO-Center Stats：当年 YTD 已定价 IPO 家数与融资额。

    口径：市值 ≥ $50mm 的美国 IPO；同比为与去年同期比较。
    返回 {"count": int, "proceeds_bil": float}；失败抛异常由调用方兜底。"""
    url = "https://www.renaissancecapital.com/IPO-Center/Stats"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    text = re.sub(r"<script.*?</script>", " ", r.text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    m1 = re.search(r"There have been (\d+) IPOs priced this year(?:, a ([+-]?[\d.]+)% change from last year)?", text)
    m2 = re.search(r"Total proceeds raised were \$([\d.]+) bil this year(?:, a ([+-]?[\d.]+)% change from last year)?", text)
    if not (m1 and m2):
        raise RuntimeError("Renaissance Capital YTD IPO 数据解析失败")
    return {"count": int(m1.group(1)), "proceeds_bil": float(m2.group(1)),
            "count_yoy": float(m1.group(2)) if m1.group(2) else None,
            "proceeds_yoy": float(m2.group(2)) if m2.group(2) else None,
            "source_url": url}


def fetch_all_us():
    """抓取全部美国原始序列，返回 dict(series_id -> [(date, value)]) 及估值类快照。

    单个来源失败时只记录错误、继续抓其余来源（调用方对缺失序列做 STALE 兜底）。
    """
    import traceback
    out = {}
    for sid in FRED_SERIES:
        try:
            out[sid] = fetch_fred(sid)
        except Exception:
            print(f"抓取失败 FRED {sid}", flush=True)
            traceback.print_exc()
    for name, fn in [
        ("NDX_PE_TRAILING_HIST", fetch_worldperatio_nasdaq_pe),
        ("SPX_PE_TRAILING_HIST", fetch_worldperatio_sp500_pe),
        ("NDX_SIBLIS", fetch_siblis_nasdaq),
        ("IT_SIBLIS", fetch_siblis_it_sector),
        ("CNN_FEAR_GREED", fetch_cnn_fear_greed),
        ("DAILY_PE", fetch_daily_pe),
        ("RC_IPO_YTD", fetch_renaissance_ytd),
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
