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
HIST_IPO = os.path.join(DATA_DIR, "_hist_ipo.json")

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
    }
    if len(ttm) >= 5 and ttm[-5][1]:
        extra["TTM 同比"] = f"{round((ttm[-1][1] / ttm[-5][1] - 1) * 100, 1)}%"
    ind["extra"] = extra
    ind["signal"] = compute.signal_buyback(ind["percentile_10y"])
    return ind


def build_ipo_count(raw):
    """美国 IPO 数量（年度）：Jay Ritter IPO-Statistics Table 8，情绪反向指标。

    PDF 抓取失败时沿用上次解析存档并标记 stale；全新失败（无存档）则跳过。
    百分位按 1960 起全历史计算（IPO 周期长，不用 10 年动态窗口）。
    """
    table = raw.get("RITTER_IPO")
    stale = False
    if table:
        save_json(HIST_IPO, table)
    else:
        table = load_json(HIST_IPO, None)
        if not table:
            raise RuntimeError("Ritter IPO 数据缺失且无存档")
        stale = True
    rows = {int(k): v for k, v in table["rows"].items()}
    years = sorted(rows)
    hist = [(f"{y}-01-01", rows[y]["offerings"]) for y in years]
    ly = years[-1]
    lrow = rows[ly]
    ind = base_indicator(
        "us_ipo_count", GROUP_SUPPLY, "美国 IPO 数量", "家", 0, "年度",
        "Jay Ritter · UF Warrington", "https://site.warrington.ufl.edu/ritter/ipo-data/",
        "IPO-Statistics Table 8：年度 IPO 家数 / 融资额 / 首日平均涨幅；"
        "1960-1974 引自 Ibbotson/Sindelar/Ritter (1994)；每年 1 月更新上年数据；"
        "IPO 数量为情绪反向指标：高位≈市场过热、供给增加")
    finalize(ind, hist)
    vals = [v for _, v in hist]
    pct = round(sum(1 for v in vals if v <= lrow["offerings"]) / len(vals) * 100, 1)
    ind["percentile_10y"] = pct
    ind["percentile_basis"] = f"1960–{ly} 全历史分位（{len(vals)} 个年度观测点）"
    if pct >= 80:
        ind["signal"] = {"label": f"IPO 数量处历史高位（{pct}% 分位）：供给增加、情绪偏热（反向指标偏谨慎）",
                         "tone": "warn"}
    elif pct <= 20:
        ind["signal"] = {"label": f"IPO 数量处历史低位（{pct}% 分位）：供给收缩", "tone": "info"}
    else:
        ind["signal"] = {"label": f"IPO 数量处历史中段（{pct}% 分位）", "tone": "neutral"}
    ind["extra"] = {
        "当年融资额": f"{lrow['proceeds_m'] / 100:.1f} 亿美元",
        "首日平均涨幅": f"{lrow['firstday']}%",
        "数据年份": str(ly),
        "表格更新": table.get("table_updated", ""),
    }
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
    }
    save_json(OUT_FILE, out)
    print(f"已写入 {OUT_FILE}，共 {len(indicators)} 个指标")


if __name__ == "__main__":
    main()
