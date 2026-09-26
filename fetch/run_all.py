#!/usr/bin/env python3
"""主流程：抓取 -> 计算 -> 写 data/indicators.json。

- 单个指标抓取失败时，沿用上一次成功的数据并标记 stale=true（保证每日任务不中断）。
- forward PE（Siblis）无免费长期历史：每次运行把当期值追加到
  data/_hist_*.json 自建序列，百分位待点数足够后自动启用。
- QQQ trailing PE headline 为 Robinhood 日度快照，10 年百分位沿用 worldperatio
  月度序列（双口径，页面注明）；SOXX trailing P/E 为 Robinhood 日度口径，
  自 2026-09 起按月存档（旧 iShares 口径存档已作废）。
- S&P 500 trailing PE 为 worldperatio 月度序列（单一口径）。
- S&P 500 信息技术板块 forward PE（Siblis 月度）为半导体前瞻估值的近似替代，
  自建月度存档；Yardeni 的 S&P 500 半导体行业 forward PE 更贴切但无稳定免费自动源。
- CNN 恐惧贪婪指数置于页面最顶部（市场情绪分组），日度，含 9 个子指标与约 1 年历史。
- 美国 · 股权供需：美联储 Z.1 非金融企业股票净发行（季度，负值=净回购，取反得净回购 TTM）
  与 Jay Ritter IPO-Statistics 年度 IPO 家数（情绪反向指标）。
"""
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
sys.path.insert(0, HERE)

import compute
import fetch_us

try:
    import fetch_cn
    HAVE_CN = True
except Exception:
    fetch_cn = None
    HAVE_CN = False

OUT_FILE = os.path.join(DATA_DIR, "indicators.json")
HIST_FWD = os.path.join(DATA_DIR, "_hist_qqq_forward_pe.json")
HIST_IT_FWD = os.path.join(DATA_DIR, "_hist_it_forward_pe.json")
HIST_SOXX = os.path.join(DATA_DIR, "_hist_soxx_pe.json")
# SOXX 口径已于 2026-09-26 由 iShares factsheet 切换为 Robinhood 日度：
# 旧存档口径不可比，启用新文件重新积累。
HIST_SOXX_RH = os.path.join(DATA_DIR, "_hist_soxx_pe_rh.json")
# Ritter IPO Table 8 解析结果存档（PDF 抓取失败时沿用上次解析）
IPO_YTD_HIST_FILE = os.path.join(DATA_DIR, "_hist_ipo_ytd.json")

GROUP_SENTIMENT = "市场情绪"
GROUP_VAL = "美国 · 估值"
GROUP_SUPPLY = "美国 · 股权供需"
GROUP_RATE = "美国 · 利率与通胀"
GROUP_LIQ = "美国 · 流动性"
GROUP_CN = "中国 · 宏观与地产"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def accumulate(hist_file, date_str, value):
    """追加 (date, value) 并按日期去重排序，返回完整历史。"""
    hist = load_json(hist_file, [])
    hist = [p for p in hist if p[0] != date_str]
    hist.append([date_str, value])
    hist.sort(key=lambda p: p[0])
    save_json(hist_file, hist)
    return hist


def base_indicator(id_, group, name, unit, decimals, frequency, source, source_url, method):
    return {
        "id": id_, "group": group, "name": name, "unit": unit,
        "decimals": decimals, "frequency": frequency,
        "source": source, "source_url": source_url, "method": method,
        "stale": False,
    }


def finalize(ind, history, headline_value=None, headline_date=None):
    """填充 latest/prev/delta/history/percentile 通用字段。"""
    hist = [[d, v] for d, v in history]
    ind["history"] = hist
    lv = headline_value if headline_value is not None else hist[-1][1]
    ld = headline_date if headline_date is not None else hist[-1][0]
    ind["latest"] = {"date": ld, "value": round(lv, ind["decimals"])}
    if len(hist) >= 2:
        ind["prev"] = {"date": hist[-2][0], "value": round(hist[-2][1], ind["decimals"])}
        ind["delta"] = round(hist[-1][1] - hist[-2][1], ind["decimals"])
    pct, basis = compute.percentile(history, hist[-1][1])
    ind["percentile_10y"] = pct
    ind["percentile_basis"] = basis
    return ind


# ---------------- 市场情绪 ----------------

_FG_RATING_CN = {
    "extreme fear": "极度恐惧", "fear": "恐惧", "neutral": "中性",
    "greed": "贪婪", "extreme greed": "极度贪婪",
}
_FG_SUB_CN = {
    "market_momentum_sp500": "市场动量（S&P 500）",
    "market_momentum_sp125": "市场动量（S&P 125）",
    "stock_price_strength": "股价强度（新高/新低）",
    "stock_price_breadth": "市场宽度（涨跌比）",
    "put_call_options": "Put/Call 期权情绪",
    "market_volatility_vix": "波动率（VIX）",
    "market_volatility_vix_50": "波动率（VIX 50日均线）",
    "junk_bond_demand": "垃圾债需求",
    "safe_haven_demand": "避险需求",
}


def build_cnn_fear_greed(raw):
    d = raw["CNN_FEAR_GREED"]
    ind = base_indicator(
        "us_fear_greed", GROUP_SENTIMENT, "CNN 恐惧贪婪指数", "", 0, "日度",
        "CNN Business", "https://www.cnn.com/markets/fear-and-greed",
        "0=极度恐惧，100=极度贪婪；综合 7 大类子指标计算；"
        "CNN 官方 JSON 接口（production.dataviz.cnn.io），免 key；"
        "历史序列为接口公开的约 1 年日度数据")
    finalize(ind, d["history"], headline_value=d["score"], headline_date=d["asof"])
    rating_cn = _FG_RATING_CN.get(d["rating"], d["rating"])
    ind["signal"] = {"label": f"{rating_cn}（{d['score']:.0f}/100）", "tone": "neutral"}
    ind["extra"] = {_FG_SUB_CN.get(k, k):
                    f"{_FG_RATING_CN.get(v['rating'], v['rating'])} {v['score']:.0f}"
                    for k, v in d["subs"].items()}
    return ind


# ---------------- 美国 · 估值 ----------------

def build_qqq_pe(raw):
    hist = raw["NDX_PE_TRAILING_HIST"]
    d = raw["DAILY_PE"]["QQQ"]
    ind = base_indicator(
        "us_qqq_pe", GROUP_VAL, "QQQ / Nasdaq-100 Trailing PE", "x", 2, "日度",
        d["src"], "https://api.robinhood.com/fundamentals/",
        "Headline 为日度快照（Robinhood 口径，交易所日期）；10 年百分位沿用 worldperatio "
        "月度序列计算。双口径已注明：headline 与百分位基数口径不同，不可直接比较绝对值")
    finalize(ind, hist, headline_value=d["pe"], headline_date=d["date"])
    # 跨口径：不展示基于月度序列的 delta，避免误导
    ind["delta"] = None
    ind["prev"] = None
    ind["signal"] = compute.signal_pe(ind["percentile_10y"])
    extra = {"月度序列最新（worldperatio 口径）":
             f"{hist[-1][1]}（{hist[-1][0]}）"}
    if d.get("high_52w"):
        extra["52周最高"] = f"{d['high_52w']:.2f}（{d.get('high_52w_date')}）"
    if d.get("low_52w"):
        extra["52周最低"] = f"{d['low_52w']:.2f}（{d.get('low_52w_date')}）"
    ind["extra"] = extra
    return ind


def build_qqq_forward_pe(raw):
    s = raw["NDX_SIBLIS"]
    asof = s["asof"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hist = accumulate(HIST_FWD, asof, s["forward"])
    ind = base_indicator(
        "us_qqq_forward_pe", GROUP_VAL, "QQQ / Nasdaq-100 Forward PE", "x", 2, "月度",
        "Siblis Research", "https://siblisresearch.com/data/nasdaq-100-pe-ratio/",
        "forward PE 无免费长期历史，本序列自首次抓取起每月自动存档、逐步积累；口径固定为 Siblis")
    finalize(ind, [(d, v) for d, v in hist])
    n = len(hist)
    if ind["percentile_10y"] is None or n < 12:
        ind["percentile_10y"] = None
        ind["percentile_basis"] = f"积累中（{n} 个月度点，满 12 个月后启用百分位）"
        ind["signal"] = {"label": "历史序列积累中（每月自动存档）", "tone": "neutral"}
    else:
        ind["signal"] = compute.signal_pe(ind["percentile_10y"])
    ind["extra"] = {"同期 Trailing PE（Siblis 口径）": s["trailing"],
                    "CAPE（Siblis 口径）": s["cape"]}
    return ind


def build_it_forward_pe(raw):
    """S&P 500 信息技术板块 forward PE：半导体前瞻估值的近似替代。"""
    s = raw["IT_SIBLIS"]
    asof = s["asof"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hist = accumulate(HIST_IT_FWD, asof, s["forward"])
    ind = base_indicator(
        "us_it_forward_pe", GROUP_VAL, "S&P 500 信息技术板块 Forward PE", "x", 2, "月度",
        "Siblis Research", "https://siblisresearch.com/data/sector-pe-earnings/",
        "SOXX / 半导体行业 forward PE 无公开免费的稳定自动来源，"
        "此处以 S&P 500 信息技术板块 forward PE 为近似替代 "
        "（Yardeni 的 S&P 500 半导体行业 forward PE 口径更贴切，但无稳定免费自动抓取）；"
        "forward PE 无免费长期历史，本序列自首次抓取起每月自动存档、逐步积累；口径固定为 Siblis")
    finalize(ind, [(d, v) for d, v in hist])
    n = len(hist)
    if ind["percentile_10y"] is None or n < 12:
        ind["percentile_10y"] = None
        ind["percentile_basis"] = f"积累中（{n} 个月度点，满 12 个月后启用百分位）"
        ind["signal"] = {"label": "历史序列积累中（每月自动存档）", "tone": "neutral"}
    else:
        ind["signal"] = compute.signal_pe(ind["percentile_10y"])
    ind["extra"] = {"同期 Trailing PE（Siblis 口径）": s["trailing"],
                    "口径说明": "S&P 500 信息技术板块 ≈ 半导体前瞻估值的近似替代，非 SOXX 官方口径"}
    return ind


def build_soxx_pe(raw):
    d = raw["DAILY_PE"]["SOXX"]
    asof = d["date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # 按月存档（取当月首日为 key），与旧 iShares 口径存档隔离
    hist = accumulate(HIST_SOXX_RH, asof[:7] + "-01", d["pe"])
    ind = base_indicator(
        "us_soxx_pe", GROUP_VAL, "SOXX Trailing P/E", "x", 2, "日度",
        d["src"], "https://api.robinhood.com/fundamentals/",
        "日度 trailing P/E（Robinhood 口径）；无公开免费长期历史，"
        "本序列自 2026-09 起按月自动存档（2026-09-26 前为 iShares 口径，已作废隔离）")
    finalize(ind, [(dd, v) for dd, v in hist],
             headline_value=d["pe"], headline_date=asof)
    n = len(hist)
    try:
        age_days = (datetime.now(timezone.utc).date()
                    - datetime.strptime(asof, "%Y-%m-%d").date()).days
    except ValueError:
        age_days = 0
    if age_days > 7:
        ind["signal"] = {"label": f"日度数据已 {age_days} 天未更新（截至 {asof}），请检查抓取",
                         "tone": "warn"}
    elif ind["percentile_10y"] is None or n < 12:
        ind["percentile_10y"] = None
        ind["percentile_basis"] = f"积累中（{n} 个月度点，满 12 个月后启用百分位）"
        ind["signal"] = {"label": "历史序列积累中（每月自动存档）", "tone": "neutral"}
    else:
        ind["signal"] = compute.signal_pe(ind["percentile_10y"])
    extra = {}
    if d.get("high_52w"):
        extra["52周最高"] = f"{d['high_52w']:.2f}（{d.get('high_52w_date')}）"
    if d.get("low_52w"):
        extra["52周最低"] = f"{d['low_52w']:.2f}（{d.get('low_52w_date')}）"
    if extra:
        ind["extra"] = extra
    return ind


def build_sp500_pe(raw):
    hist = raw["SPX_PE_TRAILING_HIST"]
    ind = base_indicator(
        "us_sp500_pe", GROUP_VAL, "S&P 500 Trailing PE", "x", 2, "月度",
        "worldperatio", "https://www.worldperatio.com/index/sp-500/",
        "月度 trailing PE（单一口径）；百分位=当前值在动态 10 年窗口月度观测中的分位")
    finalize(ind, hist)
    ind["signal"] = compute.signal_pe(ind["percentile_10y"])
    return ind


# ---------------- 美国 · 股权供需 ----------------
def build_net_buybacks(raw):
    """非金融企业净回购（TTM）：美联储 Z.1 股票净发行取反。

    BOGZ1FU103164103Q 为季度 NSA 真实季度流量（百万美元，净发行口径，负值=净回购）；
    TTM = -(近 4 季之和) / 100，单位亿美元。非 S&P 500 毛回购口径。
    """
    hist = raw["BOGZ1FU103164103Q"]
    ttm = []
    for i in range(3, len(hist)):
        q = hist[i - 3:i + 1]
        ttm.append((q[-1][0], round(-sum(v for _, v in q) / 100)))
    ind = base_indicator(
        "us_net_buybacks", GROUP_SUPPLY, "非金融企业净回购（TTM）", "亿美元", 0, "季度",
        "FRED · Z.1", "https://fred.stlouisfed.org/series/BOGZ1FU103164103Q",
        "美联储资金流量表 Z.1：非金融企业股票净发行（新股发行 − 回购 − 现金并购注销等），"
        "季度 NSA 真实季度流量；负值=净回购，取反得净回购 TTM；"
        "与 S&P 500 总回购（毛值、含金融股、约 $1T/年）口径不同，此处为全口径非金融企业的净值")
    finalize(ind, ttm)
    qdate, qval = hist[-1]
    extra = {
        "最近季度净发行": f"{qval / 100:.0f} 亿美元（正=净发行，负=净回购）",
        "数据季度": qdate[:7],
        "下期数据": "2026年Q3，预计2026-12-10发布（Z.1每季度发布一次）",
    }
    if len(ttm) >= 5 and ttm[-5][1]:
        extra["TTM 同比"] = f"{round((ttm[-1][1] / ttm[-5][1] - 1) * 100, 1)}%"
    ind["extra"] = extra
    ind["signal"] = compute.signal_buyback(ind["percentile_10y"])
    return ind


def build_ipo_count(raw):
    """美国 IPO（当年累计）：Renaissance Capital IPO-Center Stats。

    每日更新的当年 YTD 已定价 IPO 家数与融资额（口径：市值 ≥ $50mm 的美国 IPO），
    同比为与去年同期比较。抓取失败时沿用本地 YTD 快照存档并标记 stale；
    全新失败（无存档）则跳过。当年累计口径不做历史百分位。
    """
    ytd = raw.get("RC_IPO_YTD") or {}
    hist = load_json(IPO_YTD_HIST_FILE, [])
    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    stale = False
    if ytd.get("count"):
        hist = [h for h in hist if h.get("date") != today]
        hist.append({"date": today, "count": ytd["count"],
                     "proceeds_bil": ytd["proceeds_bil"],
                     "count_yoy": ytd.get("count_yoy"),
                     "proceeds_yoy": ytd.get("proceeds_yoy")})
        hist = hist[-400:]
        save_json(IPO_YTD_HIST_FILE, hist)
    elif hist:
        stale = True
    else:
        raise RuntimeError("Renaissance YTD IPO 无数据且无历史存档")
    last = hist[-1]
    curryear = today[:4]
    ind = base_indicator(
        "us_ipo_count", GROUP_SUPPLY, f"美国 IPO（{curryear}年累计）", "家", 0, "日度",
        "Renaissance Capital", "https://www.renaissancecapital.com/IPO-Center/Stats",
        "当年累计已定价 IPO 家数 / 融资额（口径：市值≥$5000万的美国 IPO）；"
        "同比为与去年同期比较；IPO 融资是股权供给的重要来源，融资额大增时对市场有抽水效应")
    finalize(ind, [(h["date"], h["count"]) for h in hist])
    ind["percentile_10y"] = None
    ind["percentile_basis"] = "当年累计口径：与去年同期比，不做历史百分位"
    cy, py = last.get("count_yoy"), last.get("proceeds_yoy")
    extra = {
        "累计融资额": f"{last['proceeds_bil'] * 10:.0f} 亿美元（${last['proceeds_bil']:.1f}B）",
        "统计口径": "市值≥$5000万的美国IPO",
    }
    if cy is not None:
        extra["家数同比"] = f"{cy:+.1f}%"
    if py is not None:
        extra["融资额同比"] = f"{py:+.1f}%"
    ind["extra"] = extra
    if py is not None and py >= 100:
        ind["signal"] = {"label": f"{curryear}年IPO融资${last['proceeds_bil']:.1f}B（同比{py:+.0f}%）：巨型IPO主导，股权供给放量",
                         "tone": "warn"}
    elif py is not None and py <= -50:
        ind["signal"] = {"label": f"{curryear}年IPO融资${last['proceeds_bil']:.1f}B（同比{py:+.0f}%）：融资明显萎缩",
                         "tone": "info"}
    else:
        ind["signal"] = {"label": f"{curryear}年至今已定价 {last['count']} 家",
                         "tone": "neutral"}
    if stale:
        ind["stale"] = True
    return ind


# ---------------- 美国 · 利率与通胀 ----------------

def build_yield(raw):
    hist = raw["DGS10"]
    ind = base_indicator(
        "us_10y_yield", GROUP_RATE, "美国10年期国债收益率", "%", 2, "日度",
        "FRED · DGS10", "https://fred.stlouisfed.org/series/DGS10",
        "百分位=当前收益率在近10年交易日中的分位；分位高=收益率偏高=债券相对便宜")
    finalize(ind, hist)
    ind["signal"] = compute.signal_yield(ind["percentile_10y"])
    return ind


def _inflation(id_, name, series, source_url):
    hist = series
    yoy, base_date = compute.yoy_monthly(hist)
    ind = base_indicator(
        id_, GROUP_RATE, name, "%", 2, "月度",
        "FRED", source_url,
        "同比=最新指数 / 12 个月前指数 - 1；与美联储 2% 目标对照")
    ind["history"] = [[d, v] for d, v in hist]
    ind["latest"] = {"date": hist[-1][0], "value": yoy}
    ind["extra"] = {"指数值": round(hist[-1][1], 2), "基期": base_date}
    ind["percentile_10y"] = None
    ind["percentile_basis"] = "通胀看同比与 2% 目标的距离，不做历史百分位"
    ind["signal"] = compute.signal_inflation(yoy)
    return ind


def build_cpi(raw):
    return _inflation("us_cpi_yoy", "美国 CPI 同比", raw["CPIAUCSL"],
                      "https://fred.stlouisfed.org/series/CPIAUCSL")


def build_pce(raw):
    return _inflation("us_pce_yoy", "美国 PCE 同比", raw["PCEPI"],
                      "https://fred.stlouisfed.org/series/PCEPI")


# ---------------- 美国 · 流动性 ----------------

def _liquidity(id_, name, hist, unit, decimals, scale, source_url, note):
    scaled = [(d, v / scale) for d, v in hist]
    ind = base_indicator(
        id_, GROUP_LIQ, name, unit, decimals,
        "周度" if id_ in ("us_fed_assets", "us_reserves") else ("月度" if id_ == "us_m2" else "日度"),
        "FRED", source_url, note)
    finalize(ind, scaled)
    ind["percentile_10y"] = None
    ind["percentile_basis"] = "流动性看水平与趋势，不做历史百分位"
    t3 = compute.pct_change_3m(scaled)
    if t3:
        ind["extra"] = {f"近3个月变化": f"{t3['pct']}%",
                        "基准日期": t3["base_date"]}
    ind["signal"] = {"label": "跟踪中", "tone": "neutral"}
    return ind


def build_fed_assets(raw):
    ind = _liquidity("us_fed_assets", "美联储总资产", raw["WALCL"], "万亿美元", 2, 1e6,
                     "https://fred.stlouisfed.org/series/WALCL",
                     "QE/QT 的阀门：扩张=放水，收缩=缩表")
    t3 = compute.pct_change_3m([(d, v / 1e6) for d, v in raw["WALCL"]])
    if t3 and t3["pct"] < 0:
        ind["signal"] = {"label": f"近3个月缩表 {t3['pct']}%（QT 持续）", "tone": "warn"}
    elif t3:
        ind["signal"] = {"label": f"近3个月变化 {t3['pct']}%", "tone": "info"}
    return ind


def build_onrrp(raw):
    ind = _liquidity("us_onrrp", "ON RRP 用量", raw["RRPONTSYD"], "亿美元", 1, 1e2,
                     "https://fred.stlouisfed.org/series/RRPONTSYD",
                     "过剩流动性水位计：用量越低，QT 的边际冲击越直接传导至银行准备金")
    v = ind["latest"]["value"]
    if v < 1000:
        ind["signal"] = {"label": "ON RRP 已基本抽干，QT 冲击将直传准备金", "tone": "warn"}
    return ind


def build_reserves(raw):
    return _liquidity("us_reserves", "银行准备金余额", raw["WRESBAL"], "万亿美元", 2, 1e6,
                      "https://fred.stlouisfed.org/series/WRESBAL",
                      "银行体系流动性缓冲：持续下降需警惕融资压力")


def build_fedfunds(raw):
    return _liquidity("us_fedfunds", "有效联邦基金利率", raw["DFF"], "%", 2, 1,
                      "https://fred.stlouisfed.org/series/DFF",
                      "隔夜融资成本：货币政策立场的直接体现")


def build_m2(raw):
    ind = _liquidity("us_m2", "M2 货币供应", raw["M2SL"], "万亿美元", 2, 1e3,
                     "https://fred.stlouisfed.org/series/M2SL",
                     "总量背景慢变量：反映广义流动性")
    yoy, _ = compute.yoy_monthly(raw["M2SL"])
    if yoy is not None:
        ind["extra"] = dict(ind.get("extra", {}), **{"同比": f"{yoy}%"})
    return ind


# ---------------- 中国 · 宏观与地产 ----------------

def build_cn_debt(raw):
    hist = raw["BIS_DEBT"]
    ind = base_indicator(
        "cn_debt_gdp", GROUP_CN, "中国居民贷款占 GDP", "%", 1, "季度",
        "BIS · 总信贷统计", "https://www.bis.org/statistics/totcredit.htm",
        "BIS 国际口径（贷款+债务证券，含银行/非银/跨境），季度发布、滞后约半年；"
        "百分位=当前值在近10年季度观测中的分位")
    finalize(ind, hist)
    ind["signal"] = compute.signal_leverage(ind["percentile_10y"])
    ind["extra"] = {"发布滞后": "约6个月", "口径说明": "BIS 国际可比口径，大于国内住户贷款口径"}
    return ind


def _cn_income(id_, name, series, other, other_name):
    ind = base_indicator(
        id_, GROUP_CN, name, "%", 1, "季度",
        "国家统计局", "https://data.stats.gov.cn/",
        "全国居民人均可支配收入累计同比；百分位=当前值在近10年季度观测中的分位；"
        "季后约15-19天发布")
    finalize(ind, series)
    ind["signal"] = compute.signal_growth(ind["percentile_10y"])
    if other:
        ind["extra"] = {other_name: f"{other[-1][1]}%"}
    return ind


def build_cn_income_nominal(raw):
    s = raw["NBS_INCOME"]
    return _cn_income("cn_income_nominal", "中国居民人均可支配收入名义同比",
                      s["nominal"], s["real"], "同期实际同比")


def build_cn_income_real(raw):
    s = raw["NBS_INCOME"]
    return _cn_income("cn_income_real", "中国居民人均可支配收入实际同比",
                      s["real"], s["nominal"], "同期名义同比")


_TIER_NAMES = {"一线": "t1", "二线": "t2", "三线": "t3"}
_KIND_NAMES = {"new": "新建商品住宅", "old": "二手住宅"}


def build_cn_house(tier_cn, kind):
    def builder(raw):
        tier_avg = raw["TIER_AVG"][tier_cn]          # {month: {new_yoy,...}}
        months = sorted(tier_avg)
        hist = [(m + "-01", tier_avg[m][kind + "_yoy"]) for m in months]
        tier_en = _TIER_NAMES[tier_cn]
        ind = base_indicator(
            f"cn_hp_{tier_en}_{kind}", GROUP_CN,
            f"{tier_cn}城市{_KIND_NAMES[kind]}价格同比", "%", 2, "月度",
            "东方财富 / 国家统计局",
            "https://datacenter-web.eastmoney.com/",
            "历史序列为研究口径：70城分线简单平均（2011年起）；"
            "当期值优先用统计局解读的官方加权口径；百分位=当前值在近10年月度观测中的分位")
        # 当期值：官方解读优先
        jiedu = raw.get("JIEDU")
        latest_month = months[-1]
        headline = None
        mom = tier_avg[latest_month][kind + "_mom"]
        official = False
        if jiedu and jiedu["month"] == latest_month:
            v = jiedu["tiers"][tier_cn].get(kind + "_yoy")
            vm = jiedu["tiers"][tier_cn].get(kind + "_mom")
            if v is not None:
                headline, mom, official = v, vm if vm is not None else mom, True
        if headline is None:
            headline = tier_avg[latest_month][kind + "_yoy"]
        finalize(ind, hist, headline_value=headline,
                 headline_date=latest_month + "-01")
        ind["signal"] = compute.signal_house_price(ind["percentile_10y"])
        ind["extra"] = {"环比": f"{mom}%",
                        "当期口径": "官方加权（统计局解读）" if official else "研究口径（分线简单平均）",
                        "数据月份": latest_month}
        if official:
            ind["source"] = "国家统计局解读（当期）/ 东方财富（历史）"
        return ind
    builder.__name__ = f"build_cn_hp_{_TIER_NAMES[tier_cn]}_{kind}"
    return builder


BUILDERS = [
    ("us_fear_greed", build_cnn_fear_greed),
    ("us_qqq_pe", build_qqq_pe),
    ("us_qqq_forward_pe", build_qqq_forward_pe),
    ("us_it_forward_pe", build_it_forward_pe),
    ("us_sp500_pe", build_sp500_pe),
    ("us_soxx_pe", build_soxx_pe),
    ("us_net_buybacks", build_net_buybacks),
    ("us_ipo_count", build_ipo_count),
    ("us_10y_yield", build_yield),
    ("us_cpi_yoy", build_cpi),
    ("us_pce_yoy", build_pce),
    ("us_fed_assets", build_fed_assets),
    ("us_onrrp", build_onrrp),
    ("us_reserves", build_reserves),
    ("us_fedfunds", build_fedfunds),
    ("us_m2", build_m2),
    ("cn_debt_gdp", build_cn_debt),
    ("cn_income_nominal", build_cn_income_nominal),
    ("cn_income_real", build_cn_income_real),
] + [(f"cn_hp_{_TIER_NAMES[t]}_{k}", build_cn_house(t, k))
     for t in ("一线", "二线", "三线") for k in ("new", "old")]


# ---------------- 一句话投资建议 ----------------

def build_advice(indicators, et_str):
    """按规则把关键指标合成一句话投资建议，并列出每条依据（数据 → 结论）。

    分析逻辑参考权威框架：估值分位（Yardeni / Shiller CAPE 的均值回归思想）、
    股债性价比（Fed model：盈利收益率 vs 债券收益率）、通胀 vs 2% 目标
    （美联储政策框架）、CNN 恐惧贪婪指数（逆向情绪指标）、股权供需
    （回购/IPO 决定流通股供给）。每日随数据自动重新生成。
    """
    m = {i["id"]: i for i in indicators}

    def latest(id_):
        i = m.get(id_)
        return i["latest"]["value"] if i and isinstance(i.get("latest"), dict) else None

    def pct(id_):
        i = m.get(id_)
        p = i.get("percentile_10y") if i else None
        return p if isinstance(p, (int, float)) else None

    clauses, basis = [], []
    score = 0  # >0 偏多，<0 偏谨慎

    # 1) 估值：十年分位
    sp_p, sp_v = pct("us_sp500_pe"), latest("us_sp500_pe")
    qqq_p, qqq_v = pct("us_qqq_pe"), latest("us_qqq_pe")
    vp, vv, vname = (sp_p, sp_v, "S&P 500") if sp_p is not None else (qqq_p, qqq_v, "Nasdaq-100")
    if vp is not None and vv is not None:
        if vp >= 70:
            clauses.append(f"美股估值处十年高位（{vname} trailing PE {vv}，{vp}%分位）")
            basis.append({"数据": f"{vname} trailing PE {vv}，十年{vp}%分位",
                          "结论": "估值偏高，未来长期回报空间被压缩（Yardeni / Shiller 估值框架）"})
            score -= 1
        elif vp <= 30:
            clauses.append(f"美股估值处十年低位（{vname} trailing PE {vv}，{vp}%分位）")
            basis.append({"数据": f"{vname} trailing PE {vv}，十年{vp}%分位",
                          "结论": "估值偏便宜，安全边际较好"})
            score += 1

    # 2) 利率：股债性价比（Fed model 逻辑）
    y10, y10p = latest("us_10y_yield"), pct("us_10y_yield")
    if y10 is not None:
        if y10 >= 4.5 or (y10p is not None and y10p >= 90):
            clauses.append(f"10 年期美债收益率 {y10}% 处历史高位")
            basis.append({"数据": f"10 年期收益率 {y10}%（十年{y10p}%分位）" if y10p is not None else f"10 年期收益率 {y10}%",
                          "结论": "债券收益率走高，股票相对性价比下降（Fed model：盈利收益率 vs 债券收益率）"})
            score -= 1
        elif y10 <= 2.5:
            clauses.append(f"10 年期美债收益率仅 {y10}%，利率环境友好")
            basis.append({"数据": f"10 年期收益率 {y10}%",
                          "结论": "无风险利率低，利于股票估值扩张"})
            score += 1

    # 3) 通胀与货币政策（美联储 2% 目标框架）
    cpi, pce, ff = latest("us_cpi_yoy"), latest("us_pce_yoy"), latest("us_fedfunds")
    if any(x is not None and x > 3.0 for x in (cpi, pce)):
        clauses.append(f"通胀仍远高于 2% 目标（CPI {cpi}%、PCE {pce}%）")
        basis.append({"数据": f"CPI {cpi}%、PCE {pce}%，联邦基金利率 {ff}%",
                      "结论": "通胀超目标且政策利率维持高位，货币政策难转向宽松"})
        score -= 1
    elif cpi is not None and pce is not None and cpi <= 2.5 and pce <= 2.5:
        clauses.append("通胀回落至目标附近")
        basis.append({"数据": f"CPI {cpi}%、PCE {pce}%",
                      "结论": "通胀受控，政策有宽松空间"})
        score += 1

    # 4) 情绪：CNN 恐惧贪婪（逆向指标）
    cnn = latest("us_fear_greed")
    if cnn is not None:
        if cnn <= 45:
            clauses.append(f"恐惧贪婪指数 {cnn:.0f} 处恐惧区间")
            basis.append({"数据": f"CNN 恐惧贪婪指数 {cnn:.0f}",
                          "结论": "市场情绪偏恐惧，逆向指标偏正面（别人恐惧时可更积极）"})
            score += 1
        elif cnn >= 55:
            clauses.append(f"恐惧贪婪指数 {cnn:.0f} 处贪婪区间")
            basis.append({"数据": f"CNN 恐惧贪婪指数 {cnn:.0f}",
                          "结论": "市场情绪偏热，逆向指标偏谨慎"})
            score -= 1

    # 5) 股权供需：企业净回购
    bbp, bbv = pct("us_net_buybacks"), latest("us_net_buybacks")
    if bbp is not None and bbv is not None:
        if bbp <= 20:
            amt = f"净发行 {-bbv:.0f}" if bbv < 0 else f"净回购 {bbv:.0f}"
            clauses.append(f"企业股权供给压力大（TTM{amt}亿美元，{bbp}%分位）")
            basis.append({"数据": f"非金融企业股票净回购 TTM {bbv:.0f} 亿美元（十年{bbp}%分位）",
                          "结论": "企业回购是美股重要买盘，转弱意味着股权供给相对增加"})
            score -= 1
        elif bbp >= 80:
            clauses.append(f"企业回购力度强（TTM 净回购 {bbv:.0f} 亿美元，{bbp}%分位）")
            basis.append({"数据": f"非金融企业股票净回购 TTM {bbv:.0f} 亿美元（十年{bbp}%分位）",
                          "结论": "回购提供持续买盘，对股价有支撑"})
            score += 1

    if score <= -2:
        stance, action = "偏谨慎", "可适当降低权益仓位、增配短久期债券或现金，等待更好的风险回报比"
    elif score >= 2:
        stance, action = "偏积极", "可在市场回调中分批布局优质资产"
    else:
        stance, action = "中性", "保持均衡配置，不追高也不杀跌"

    text = f"综合建议{stance}：" + "；".join(clauses) + f"。{action}。"
    return {"text": text, "stance": stance, "score": score,
            "basis": basis, "generated_at_et": et_str}


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    prev = load_json(OUT_FILE, {})
    prev_map = {i["id"]: i for i in prev.get("indicators", [])}

    raw = {}
    try:
        raw = fetch_us.fetch_all_us()
    except Exception:
        traceback.print_exc()
        print("抓取层整体失败，将全部沿用上次数据", flush=True)

    if HAVE_CN:
        try:
            cn_raw = fetch_cn.fetch_all_cn()
            raw.update(cn_raw)
            if "EF_HOUSE" in raw:
                raw["TIER_AVG"] = fetch_cn.tier_simple_avg(raw["EF_HOUSE"])
        except Exception:
            traceback.print_exc()
            print("中国抓取层失败，相关指标将沿用旧值", flush=True)

    indicators = []
    for ind_id, builder in BUILDERS:
        try:
            ind = builder(raw)
            indicators.append(ind)
            print(f"OK  {ind['id']}: {ind['latest']}")
        except Exception:
            traceback.print_exc()
            if ind_id in prev_map:
                found = dict(prev_map[ind_id])
                found["stale"] = True
                indicators.append(found)
                print(f"STALE {ind_id}（沿用上次数据）")
            else:
                print(f"SKIP {ind_id}（无历史可沿用）")

    now_utc = datetime.now(timezone.utc)
    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    out = {
        "generated_at_utc": now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        "generated_at_et": et.strftime("%Y-%m-%d %H:%M ET"),
        "group_order": [GROUP_SENTIMENT, GROUP_VAL, GROUP_SUPPLY, GROUP_RATE, GROUP_LIQ, GROUP_CN],
        "indicators": indicators,
        "advice": build_advice(indicators, et.strftime("%Y-%m-%d %H:%M ET")),
    }
    save_json(OUT_FILE, out)
    print(f"已写入 {OUT_FILE}，共 {len(indicators)} 个指标")


if __name__ == "__main__":
    main()
