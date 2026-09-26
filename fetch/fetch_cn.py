#!/usr/bin/env python3
"""中国指标抓取：居民贷款/GDP（BIS）、居民收入（NBS 新版 API）、70 城房价（东财 + NBS 解读）。

全部免费、无需 key。NBS/东财可能对境外 IP 限流，调用方需做失败兜底（沿用旧值）。
"""
import re
import time
from datetime import date

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "Chrome/124.0.0.0 Safari/537.36")
TIMEOUT = 45

# ---------------- 城市分线（官方口径，2026-01 发布 PDF） ----------------
TIER1 = ["北京", "上海", "广州", "深圳"]
TIER2 = ["天津", "石家庄", "太原", "呼和浩特", "沈阳", "大连", "长春", "哈尔滨",
         "南京", "杭州", "宁波", "合肥", "福州", "厦门", "南昌", "济南", "青岛",
         "郑州", "武汉", "长沙", "南宁", "海口", "重庆", "成都", "贵阳", "昆明",
         "西安", "兰州", "西宁", "银川", "乌鲁木齐"]
TIER3 = ["唐山", "秦皇岛", "包头", "丹东", "锦州", "吉林", "牡丹江", "无锡", "徐州",
         "扬州", "温州", "金华", "蚌埠", "安庆", "泉州", "九江", "赣州", "烟台",
         "济宁", "洛阳", "平顶山", "宜昌", "襄阳", "岳阳", "常德", "韶关", "湛江",
         "惠州", "桂林", "北海", "三亚", "泸州", "南充", "遵义", "大理"]
TIERS = {"一线": TIER1, "二线": TIER2, "三线": TIER3}


def _quarter_end(qstr):
    """'2026-Q1' -> '2026-03-31'；'202602SS' -> '2026-06-30'。"""
    if qstr.endswith("SS"):
        y, q = int(qstr[:4]), int(qstr[4:6])
    else:
        y, q = int(qstr[:4]), int(qstr[6])
    return {1: f"{y}-03-31", 2: f"{y}-06-30",
            3: f"{y}-09-30", 4: f"{y}-12-31"}[q]


# ---------------- 1. BIS：居民贷款占 GDP ----------------

def fetch_bis_household_debt():
    """BIS WS_TC v2.0，中国家庭部门信贷/GDP（%，季度）。返回 [(date, value)]。"""
    url = ("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0/"
           "Q.CN.H.A.M.770.A")
    r = requests.get(
        url,
        params={"startPeriod": "2006-Q1", "detail": "dataonly",
                "format": "jsondata"},
        headers={"Accept": "application/vnd.sdmx.data+json",
                 "User-Agent": UA},
        timeout=TIMEOUT)
    r.raise_for_status()
    ds = r.json()["data"]
    obs_dim = ds["structure"]["dimensions"]["observation"][0]["values"]
    series = ds["dataSets"][0]["series"]
    if len(series) != 1:
        raise ValueError(f"BIS 返回 {len(series)} 条序列，期望 1 条")
    key = next(iter(series))
    rows = []
    for idx, val in series[key]["observations"].items():
        q = obs_dim[int(idx)]["id"]          # 如 2026-Q1
        v = val[0]
        if v is None or v == "":
            continue
        rows.append((_quarter_end(q), float(v)))
    rows.sort()
    if not rows:
        raise ValueError("BIS 未返回有效观测值")
    return rows


# ---------------- 2. NBS：居民人均可支配收入 ----------------

_NBS_API = ("https://data.stats.gov.cn/dg/website/publicrelease/web/external/"
            "stream/esData")
_NBS_H = {"Content-Type": "application/json",
          "Referer": "https://data.stats.gov.cn/dg/website/page.html",
          "User-Agent": UA}
_NBS_CID = "ec2d57ed282f456e8d025aff035b4fad"          # 全国居民人均收入情况
_NBS_ROOT = "a94b8b7365a94874968cabbe392cf679"        # 季度数据根
_NBS_IND_REAL = "7abcbb6f7c844b669d43da985d3f6ff2"     # 累计增长（实际 %）
_NBS_IND_VAL = "bb5699c5ad534b568cca7c946227225a"      # 累计值（元，用于算名义）


def _nbs_query(indicator_id, dts="201301SS-202602SS"):
    body = {"cid": _NBS_CID, "indicatorIds": [indicator_id], "daCatalogId": "",
            "das": [{"text": "全国", "value": "000000000000"}],
            "showType": "1", "dts": [dts], "rootId": _NBS_ROOT}
    r = requests.post(_NBS_API, json=body, headers=_NBS_H, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    if d.get("state") != 20000 or not d.get("data"):
        raise ValueError(f"NBS 接口异常 state={d.get('state')}")
    rows = []
    for p in d["data"]:
        try:
            v = float(p["values"][0]["value"])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        rows.append((_quarter_end(p["code"]), v))
    rows.sort()
    if not rows:
        raise ValueError("NBS 未返回有效数据")
    return rows


def fetch_nbs_income():
    """返回 {'real': [(date, 实际同比%)], 'nominal': [(date, 名义同比%)]}。"""
    real = _nbs_query(_NBS_IND_REAL)
    vals = _nbs_query(_NBS_IND_VAL)
    vmap = dict(vals)
    nominal = []
    for dstr, v in vals:
        y, m = int(dstr[:4]), int(dstr[5:7])
        prev = f"{y - 1}-{m:02d}-{dstr[8:10]}"
        if prev in vmap and vmap[prev]:
            nominal.append((dstr, round(v / vmap[prev] * 100 - 100, 2)))
    if not nominal:
        raise ValueError("名义增速计算失败")
    return {"real": real, "nominal": nominal}


# ---------------- 3a. 东财：70 城房价指数 ----------------

_EF_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EF_COLS = ("CITY,REPORT_DATE,FIRST_COMHOUSE_SAME,FIRST_COMHOUSE_SEQUENTIAL,"
            "SECOND_HOUSE_SAME,SECOND_HOUSE_SEQUENTIAL")


def fetch_eastmoney_house():
    """分页拉全量 70 城指数。返回 {month: {city: {'new_yoy','new_mom','old_yoy','old_mom'}}}（指数值）。"""
    out = {}
    page = 1
    while True:
        params = {"reportName": "RPT_ECONOMY_HOUSE_PRICE",
                  "columns": _EF_COLS,
                  "filter": "(REPORT_DATE>='2011-01-01 00:00:00')",
                  "pageNumber": page, "pageSize": 500,
                  "sortColumns": "REPORT_DATE", "sortTypes": -1}
        r = requests.get(_EF_URL, params=params,
                         headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        rows = r.json()["result"]["data"] or []
        if not rows:
            break
        for x in rows:
            month = x["REPORT_DATE"][:7]
            try:
                rec = {"new_yoy": float(x["FIRST_COMHOUSE_SAME"]),
                       "new_mom": float(x["FIRST_COMHOUSE_SEQUENTIAL"]),
                       "old_yoy": float(x["SECOND_HOUSE_SAME"]),
                       "old_mom": float(x["SECOND_HOUSE_SEQUENTIAL"])}
            except (TypeError, ValueError):
                continue
            out.setdefault(month, {})[x["CITY"]] = rec
        if len(rows) < 500:
            break
        page += 1
        if page > 60:  # 熔断
            break
        time.sleep(0.3)
    if not out:
        raise ValueError("东财未返回数据")
    return out


def tier_simple_avg(house_data):
    """分线简单平均 -> {tier: {month: {'new_yoy','new_mom','old_yoy','old_mom'}}}（涨跌幅%）。"""
    res = {t: {} for t in TIERS}
    for month in sorted(house_data):
        cities = house_data[month]
        for tier, clist in TIERS.items():
            agg = {}
            for k in ("new_yoy", "new_mom", "old_yoy", "old_mom"):
                vals = [cities[c][k] - 100 for c in clist if c in cities]
                if vals:
                    agg[k] = round(sum(vals) / len(vals), 2)
            if agg:
                res[tier][month] = agg
    return res


# ---------------- 3b. NBS 解读：官方分线聚合 ----------------

_JIEDU_LIST = "https://www.stats.gov.cn/sj/sjjd/"


def _parse_jiedu_numbers(text):
    """从解读正文提取官方分线涨跌幅。返回 {tier: {'new_mom','new_yoy','old_mom','old_yoy'}}。"""
    out = {t: {} for t in ("一线", "二线", "三线")}
    # A: "一线城市新建商品住宅销售价格环比上涨0.1%" / "由上月持平转为上涨0.1%" / "持平"
    pat_a = re.compile(
        r"(一|二|三)线城市(新建商品住宅|二手住宅)销售价格(环比|同比)"
        r"(?:由上月[^，。]*?转为)?(上涨|下降|持平)([0-9]+\.?[0-9]*)?%")
    # B: "二、三线城市新建商品住宅销售价格同比分别下降2.7%和4.1%"
    pat_b = re.compile(
        r"二、三线城市(新建商品住宅|二手住宅)销售价格(环比|同比)"
        r"分别(上涨|下降)([0-9]+\.?[0-9]*)%和([0-9]+\.?[0-9]*)%")
    kind_map = {"新建商品住宅": "new", "二手住宅": "old"}
    per_map = {"环比": "mom", "同比": "yoy"}

    def val(word, num):
        if word == "持平" or num is None:
            return 0.0
        v = float(num)
        return v if word == "上涨" else -v

    for m in pat_a.finditer(text):
        tier, kind, per, word, num = m.groups()
        out[tier + "线"][kind_map[kind] + "_" + per_map[per]] = val(word, num)
    for m in pat_b.finditer(text):
        kind, per, word, n2, n3 = m.groups()
        k = kind_map[kind] + "_" + per_map[per]
        out["二线"][k] = val(word, n2)
        out["三线"][k] = val(word, n3)
    return out


def fetch_nbs_jiedu():
    """找最新一期房价解读，返回 {'month': 'YYYY-MM', 'tiers': {...}, 'url': ...}。"""
    r = requests.get(_JIEDU_LIST, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    html = r.content.decode("utf-8", errors="ignore")
    links = re.findall(
        r'href="(\./\d{6}/[^"]+\.html)"[^>]*>([^<]*商品住宅销售价格变动情况统计数据[^<]*)<',
        html)
    best = None
    for href, title in links:
        m = re.search(r"(\d{4})年(\d{1,2})月份", title)
        if not m:
            continue
        month = f"{m.group(1)}-{int(m.group(2)):02d}"
        if best is None or month > best[0]:
            best = (month, href)
    if not best:
        raise ValueError("未找到房价解读文章")
    month, href = best
    url = "https://www.stats.gov.cn/sj/sjjd/" + href[2:]
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    html = r.content.decode("utf-8", errors="ignore")
    paras = re.findall(r"<p[^>]*>(.*?)</p>", html, re.S)
    text = re.sub(r"\s+", " ",
                  " ".join(re.sub(r"<[^>]+>", "", p) for p in paras))
    tiers = _parse_jiedu_numbers(text)
    # 完整性校验：12 个数至少拿到 10 个
    n = sum(len(v) for v in tiers.values())
    if n < 10:
        raise ValueError(f"解读解析不完整，仅拿到 {n}/12 个数")
    return {"month": month, "tiers": tiers, "url": url}


def fetch_all_cn():
    """抓取全部中国原始数据。单个来源失败只记录、继续（调用方做 STALE 兜底）。"""
    import traceback
    out = {}
    for name, fn in [
        ("BIS_DEBT", fetch_bis_household_debt),
        ("NBS_INCOME", fetch_nbs_income),
        ("EF_HOUSE", fetch_eastmoney_house),
        ("JIEDU", fetch_nbs_jiedu),
    ]:
        try:
            out[name] = fn()
        except Exception:
            print(f"抓取失败 {name}", flush=True)
            traceback.print_exc()
    return out


if __name__ == "__main__":
    for name, fn in [("BIS_DEBT", fetch_bis_household_debt),
                     ("NBS_INCOME", fetch_nbs_income)]:
        try:
            data = fn()
            if isinstance(data, dict):
                for k, v in data.items():
                    print(name, k, len(v), "pts, latest", v[-1])
            else:
                print(name, len(data), "pts, latest", data[-1])
        except Exception as e:
            print(name, "FAIL", type(e).__name__, e)
