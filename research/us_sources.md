# 美国投资指标数据源调研（Dashboard 数据抓取指南）

> 目标：为 GitHub Pages 投资 dashboard 提供**免费、公开、准确、可程序化抓取**的美国指标数据源。
> 原则：官方/权威优先（FRED、美国财政部、BLS、BEA、Nasdaq/iShares 官方）；准确性 > 便利性；免 key 优先。
> 调研日期：2026-09-26。所有 endpoint/series 均经实际验证（curl / browser.open），请勿凭记忆引用未验证的 URL。

## 抓取方式总览

- **FRED 无 key CSV**：`https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>`，支持 `&cosd=YYYY-MM-DD&coed=YYYY-MM-DD` 限定日期。REST API 需要免费 key，但 CSV 下载**不需要**。
- **注意**：`id=` 逗号拼接多个 series 时，若频率混合会返回 ZIP 包（按频率拆分多个 CSV）。建议每个 series 单独请求。

---

## 一、流动性指标（已验证，2026-09-26）

推荐组合（5 个），按"判断 QQQ 走势"的信息价值排序：

| # | 指标 | FRED Series ID | 频率 | 历史起点 | 更新滞后 | 角色 |
|---|---|---|---|---|---|---|
| 1 | 美联储总资产（QE/QT 阀门） | WALCL | 周度（周三值） | 2002-12-18 | ~2 天（H.4.1 每周四发布） | 量：央行端 |
| 2 | ON RRP 用量（过剩流动性水位） | RRPONTSYD | 日度 | 2003-02-07（现行形态自 2013-09 起有意义） | 当日（NY Fed 约 13:15 ET 发布） | 量：货币市场端 |
| 3 | 银行准备金余额 | WRESBAL | 周度（周三值） | 2002-12-18 | ~2 天（H.4.1 每周四发布） | 量：银行体系端 |
| 4 | 有效联邦基金利率 | DFF | 日度 | 1954-07-01 | ~1 个工作日 | 价：融资成本 |
| 5 | M2 货币供应 | M2SL | 月度 | 1959-01-01 | ~1 个月（每月第 4 个周二 13:00 ET 发布） | 总量背景（慢变量） |

**逻辑链**：WALCL + RRPONTSYD + WRESBAL 看"量"（央行 → 货币市场 → 银行的传导链），DFF 看"价"，M2SL 看总量背景。

- 抓取：全部 `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`，无 key，HTTP 200 已实测。
- 定时任务建议：设在 **ET 下午 2 点之后**运行（RRPONTSYD 当日值、DFF/SOFR 前一日值已出；WALCL/WRESBAL 每周四更新；M2SL 每月更新，顺带刷新）。
- 当前值快照（2026-09-26 实测）：WALCL = $6.75T；WRESBAL = $2.93T；RRPONTSYD = $576M（基本抽干，QT 边际冲击将直接传导至准备金）；DFF = 3.88%；M2SL = $23.34T（2026-08）。

### 不推荐 / 备选

- **SOFR（FRED series `SOFR`，备选）**：与 DFF 高度相关（日常仅差几个 bp），且历史自 2018-04 起**不足 10 年**。信息增量有限，不建议与 DFF 同时放。
- **WM2NS（不推荐）**：虽为周度 M2，但非季调且实际只随月度 H.6 推进（滞后 ~22 天），频率优势是假象；M2SL 更标准。
- **RRPONTSYAWARD（ON RRP 中标利率，不推荐）**：这是利率而非用量，对流动性水位判断无增量信息。

---

## 二、10 年期美债收益率（已验证，2026-09-26）

### 推荐：FRED `DGS10`（首选）

- **抓取**：`https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10` —— 无 key CSV，✅ 已实测（HTTP 200，268KB）。
- **格式**：`observation_date,DGS10` 两列 CSV，**1962-01-02 起，每交易日，16,889 行**。
- **更新频率**：每日，约滞后 1 个交易日（2026-09-26 实测最新值为 2026-09-24 = 5.18%）。
- **升级选项**：FRED REST API `https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key=...&file_type=json` —— 必须免费 key（注册：https://fred.stlouisfed.org/docs/api/api_key.html），限流 120 req/分钟。适合 key 存 GitHub Secret、需要统一 JSON 接口或修正历史（vintages）时。
- **贵/便宜判断**：用 DGS10 自身 10 年历史直接算百分位 / Z-score 即可。

### 备用/交叉验证：美国财政部官方 XML Feed（免 key，已验证）

- **URL**：`https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=YYYY`
- 字段名：`BC_10YEAR`（另有 BC_1MONTH/BC_3MONTH/BC_6MONTH/BC_1YEAR/BC_2YEAR/BC_3YEAR/BC_5YEAR/BC_7YEAR/BC_20YEAR/BC_30YEAR）。实测 2026-09-25 `BC_10YEAR`=5.17（比 FRED 还新鲜一天；feed 头显示每个交易日美东下午更新）。
- 历史：按年参数拉取（最早到 1990）；另有归档 CSV（如 `par-yield-curve-rates-1990-2023.csv`，见 https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rate-archives）。

### 不推荐

- **fiscaldata.treasury.gov 拉收益率曲线——不要用**：`v1/v2 × daily_treasury_yield_curve / daily_treasury_par_yield_curve_rates` 四种组合已实测全部 **404**——"Daily Treasury Par Yield Curve Rates" 数据集在 fiscaldata API 中**不存在**（fiscaldata API 本身正常工作，但只有月度平均利率，无每日 par yield curve）。不要按假设路径写代码。

---

## 三、CPI 与 PCE（已验证，2026-09-26）

### 推荐：FRED 无 key CSV（首选）

| 指标 | FRED Series ID | 频率 | 历史深度（已验证） | 备注 |
|---|---|---|---|---|
| CPI-U | CPIAUCSL | 月度 | 1947-01-01 → 2026-08-01（957 行），最新 334.131 | 约滞后 2 周 |
| PCE 价格指数 | PCEPI | 月度 | 1959-01-01 → 2026-07-01（812 行），最新 131.659 | 源头即 BEA |

- 抓取：`https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`，无 key，HTTP 200 已实测。CPI 每月中旬发布上月值；PCE 约滞后 1 个月。

### 不推荐 / 仅作备选

- **BLS 公开 API（备选）**：`https://api.bls.gov/publicAPI/v2/timeseries/data/`（POST JSON），CPI-U 全项 series ID = **`CUUR0000SA0`**（1982-84=100），✅ 已验证无 key 可用（测试最新 2026-08=334.980）。但**无 key 每天仅 25 次、按 IP 计，GitHub Actions 共享出口 IP 极易撞限额**；免费注册 key 后 500 次/天。仅在需要 BLS 独有细分 CPI 时用，且建议注册 key。
- **BEA API（不推荐）**：`https://apps.bea.gov/api/data/` **必须** UserID key（免费注册，36 字符）。PCE 已被 FRED 无 key 覆盖，无增量价值；除非未来要拉 FRED 不便覆盖的 NIPA 明细。

**一句话**：收益率 DGS10 CSV + CPI/PCE 两个 FRED CSV —— **三条无 key 的 URL 搞定全部需求**，财政部 XML Feed 作次日 freshness 补充。

## 四、QQQ（Nasdaq-100）PE / Forward PE（已验证，2026-09-26）

> 核心发现：Nasdaq-100 的 PE 没有 FRED 级别的官方免费序列。推荐组合：**worldperatio（trailing + 10 年历史）+ Siblis Research（forward 当前值）**，同一指标固定用一家来源（实测各家 trailing PE 口径可差 4 个点以上：worldperatio 30.25 vs Siblis 34.24）。

### 推荐排序

| 优先级 | 来源 | 用途 | trailing/forward | 历史深度 | 抓取方式 | 费用/key |
|---|---|---|---|---|---|---|
| 1 | **worldperatio** `https://worldperatio.com/index/nasdaq-100/` | Nasdaq-100 trailing PE 当前值 + 10 年历史 | trailing | ✅ 月度，≥10 年（页面展示 1Y/5Y/10Y/20Y 均值与标准差，10Y 均值 27.39；实测当前 30.25 @2026-09-25） | HTML 内嵌 `detailPE_data` JS 数组，纯 HTML 抓取 | 免费，无 key |
| 2 | **Siblis Research** `https://siblisresearch.com/data/nasdaq-100-pe-ratio/` | Nasdaq-100 forward PE 当前值；trailing 交叉校验 | trailing + forward | ⚠️ trailing 有 10 年年终表（2016-12 至 2026-08）；**forward 仅当前值**（实测 Trailing 34.24 / Forward 22.85 / CAPE 57.82 @2026-08，月度更新） | HTML 表格 | 免费（完整日度全历史 + Excel/API 付费） |
| 3 | **Yardeni Research** `https://archive.yardeni.com/pub/zoomcharts.pdf` | S&P 500 forward PE 免费交叉验证（日度，2008 年起） | forward（仅 S&P 500） | ✅ 日度 2008 年起 | 免费 PDF，URL 稳定 | 免费，无 key |

- **分位数计算**：trailing PE 的 10 年百分位用 worldperatio 月度序列即可；forward PE 无免费 10 年历史——分位数应各自独立计算（trailing vs forward 口径不同，不可混用）。
- **Forward 10 年历史缺口**的选项：(a) Siblis 付费 DB（日度全历史 + Excel/API）；(b) 从现在起每月抓 Siblis 免费页自建积累；(c) GuruFocus premium。

### 不推荐及原因

- **multpl.com**：仅 S&P 500 系列（S&P 500 PE/Shiller PE），**无 Nasdaq-100 页面**。
- **macrotrends.net**：其 "Nasdaq PE Ratio" 页是 NDAQ 股票（交易所公司）非指数；QQQ ETF 页数据损坏（显示 PE = 0.00，TTM EPS 为空）；无 Nasdaq-100 指数 PE 页面。
- **nasdaq.com**：指数页无 P/E 展示、无历史；`api.nasdaq.com/api/quote/NDX/summary` 只返回报价字段不含 P/E（指数估值数据仅付费 Nasdaq Data Link）。
- **wsj.com**：付费墙 + 强反爬，直接抓取失败。
- **slickcharts.com**：HTTP 403（Cloudflare 反爬），且仅当前成分股快照、无历史。
- **GuruFocus**：Nasdaq-100 PE 页抓取 403，全历史需付费。
- **BTCC / stocktradersdaily**：无数据的 SEO 空壳，已排除。

---

## 五、SOXX PE / Forward PE（已验证，2026-09-26）

> 核心发现：SOXX 的 10 年 PE 历史**无公开免费来源**。iShares 官方是当前 trailing PE 的权威来源（免费），需每月存档 factsheet 自建历史。

### 推荐：iShares 官方（当前值，免费）

- **月度 factsheet PDF（已验证 URL 及内容）**：`https://www.ishares.com/us/literature/fact-sheet/soxx-ishares-semiconductor-etf-fund-fact-sheet-en-us.pdf`
  - FUND CHARACTERISTICS 栏明确列出 **"P/E Ratio : 40.03x"**（trailing，负值剔除），URL 稳定，**但只保留最新一期、无往期归档**。
- **产品页**：`https://www.ishares.com/us/products/239705/ishares-phlx-semiconductor-etf` 的 Portfolio Characteristics 栏每日更新 P/E（trailing），JS 重度渲染。
- **务实方案**：每月抓取 factsheet 归档、自建历史序列；历史分位数暂时用较短窗口并在 dashboard 标注方法论；或 SOXX 先只展示当前值 + 与行业对照。
- **口径警告**：SOXX trailing PE 各家差异巨大——iShares 官方 40.03 vs etfdb 64.10 vs barchart 66.24 vs stockanalysis 40.09。**Dashboard 必须固定用 iShares 官方口径**，不要混用。

### 备选快照源（仅当前值、无历史，仅交叉参考）

- stockanalysis.com/etf/soxx/（PE 40.09，免费 HTML）；etfdb.com / barchart SOXX 估值栏。`stockanalysis.com/etf/soxx/statistics/` 路径不存在（404），无历史 API。

---

## 六、抓取实施要点

1. **无 key 抓取全家桶**：FRED 系列全部用 `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>&cosd=2016-01-01`（建议加 `cosd` 限定 10 年窗口，减小传输）。
2. **频率混合注意**：FRED `id=` 逗号拼接多 series 时，混合频率会返回 ZIP 包——dashboard 里**每个 series 单独请求**最稳。
3. **定时任务时间**：设在 **美东时间（ET）下午 2 点之后**（RRPONTSYD 当日值、DFF/SOFR 前一日值已出；FRED 日度序列约滞后 1 交易日）。
4. **HTML 抓取注意**：worldperatio / Siblis 是纯 HTML（无反爬，可直接抓）；iShares 产品页 JS 重度渲染——优先抓 factsheet PDF（可用 pdf 提取）或用无头浏览器。
5. **GitHub Actions 共享 IP 注意**：避免无 key 高频调用 BLS API（25 次/天按 IP 计）；FRED CSV 无此限制。
6. **口径一致性**：同一指标终身固定一家来源，并在 dashboard 标注来源与方法论（尤其 PE 类指标各家口径差异大）。

---

*调研完成：2026-09-26。所有 endpoint / series ID / URL 均经 curl 或 browser.open 实际验证。*
