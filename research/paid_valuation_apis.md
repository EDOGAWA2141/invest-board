# 付费估值数据 API 调研报告（QQQ / 半导体）

> 调研日期：2026-09-26
> 背景：免费源（worldperatio 月度、Siblis 月度、iShares 月度 PDF）太旧，用户愿意付费换实时数据；半导体接受用 SMH 替代 SOXX。
> 结论速览：**付费首选 Siblis Pro（$768/年）**解决 QQQ forward P/E；**半导体 trailing P/E 有免费的每日源（Robinhood API，已实测）**，可能不需要花钱。

---

## 推荐排序总表

| 排名 | 供应商 | 解决什么 | 频率 | 历史深度 | 价格 | 自助开通 | 备注 |
|---|---|---|---|---|---|---|---|
| ★1 | **Siblis Research Pro** | NDX/QQQ trailing + **forward** P/E（日度） | 日度 | trailing 1970+/forward 1990+ | **$768/年** | ✅ 在线下单 | 唯一同时解决 forward P/E + 深历史的；⚠️ 公开展示需另谈 redistribution 许可 |
| ★2 | **Robinhood fundamentals API（免费）** | QQQ / SMH / SOXX trailing P/E | **日度** | 无（快照） | 免费免 key | ✅ | 已实测可用；非官方接口，无 SLA |
| 3 | EODHD Fundamentals | QQQ / SMH / SOXX trailing P/E（文档化聚合口径） | 日度 | 无（快照） | ~$60/月 | ✅，免费试探 | 有合同/SLA 的付费备选 |
| 4 | Zacks quote-feed（免费） | QQQ / SMH / SOXX trailing P/E | 日度 | 无 | 免费免 key | ✅ | 交叉验证用；forward 字段为空 |
| 5 | GuruFocus | ETF trailing P/E（QQQ/SMH/SOXX） | 日度 | 较短 | ~$1,348/年起 | ✅，7 天试用 | 无 forward P/E，贵 |
| 6 | FMP Ultimate | 自算 ETF 加权 trailing P/E（DIY） | 快照 | 无 | $149/月 | ✅ | 需自己写加权逻辑，最贵 |
| ✗ | Intrinio | — | — | — | $100–200+/月 | 部分需销售 | 未找到 NDX/SOX 的 P/E tag，不可用 |
| ✗ | Nasdaq Data Link / FactSet / Bloomberg / 标普 / Morningstar | — | — | — | 企业级 | ❌ 需销售 | 无自助购买通道，不适合个人项目 |

---

## 1. Siblis Research Pro —— 付费首选（解决 QQQ forward P/E）

- **产品**："Global Equity Valuations Database"，指数加权聚合估值（市值/加总盈利），point-in-time，覆盖 91 个指数（含 NASDAQ 100）。
- **覆盖**：NDX **日度** `petrailing`（trailing P/E）、`peforward`（forward P/E）、`cape`、`pb`、`dividendyield`；forward 历史自 1990、trailing 自 1970。
- **API**：`https://siblisresearch.supabase.co/functions/v1/dataapi/v1/`
  - `GET /v1/indices`（指数列表）、`GET /v1/<TICKER>/<ratio>?from=&to=`、`GET /v1/<TICKER>/<ratio>/stats`（**直接返回当前值 + 均值/中位数/百分位**，10 年百分位可直接拿）、`GET /v1/<TICKER>/download`（批量 CSV，Enterprise 才有）
  - 文档：https://siblisresearch.com/api-guide-global-equity-valuations-database/
- **价格（自助年付）**：History Licence $349 一次性（纯历史无更新）；**Pro $768/年**（1 用户、1000 req/天、API 日度更新）；Enterprise $3,840/年；Custom 按报价（含定制指数，如加 SOX）。
- **试用**：30 天退款保证；另有免费页面（含 10 年年频历史，可署名复用）+ 免 key 免费 API（子集指数），可先验证 NDX 数据质量。
- **半导体**：标准覆盖无 SOX；Custom 计划明确支持"custom index coverage"，可发邮件问 SOX 加覆盖的报价。
- ⚠️ **关键限制**：标准许可仅限自用（模型、报告）。**把数字公开展示在 GitHub Pages dashboard 上属于 redistribution，需要单独许可**（"按你的产品和受众定价"），联系 sales@siblisresearch.com。**花钱之前先拿到 redistribution 报价**。

## 2. Robinhood fundamentals API —— 免费新发现（已实测，建议先用）

- **Endpoint**：`https://api.robinhood.com/fundamentals/?symbols=SMH,QQQ,SOXX`（批量，一次 ~100 个；单个：`/fundamentals/SMH/`）
- **字段**：`pe_ratio`（ETF 加权 trailing P/E），另有 `pb_ratio`、`dividend_yield`
- **实测值（2026-09-26 抓取，`market_date` = 2026-09-25）**：SMH `39.781860`、QQQ `35.528137`、SOXX `46.008373`
- **频率**：日度；**认证**：无，纯 JSON，本沙盒直连成功
- **限制**：快照无历史；非官方未文档化接口，无 SLA，随时可能变；各家口径不同（同日 SMH：Robinhood 39.78 vs Zacks 37.21）——**选定一家后固定使用**
- **建议用法**：每日 headline 用 Robinhood；10 年百分位继续用 worldperatio 月度序列（口径固定）；页面注明双口径

## 3. EODHD —— 付费备选（有合同的 ETF trailing P/E）

- **Endpoint**：`GET https://eodhd.com/api/fundamentals/{TICKER}?api_token=...&fmt=json&filter=Technicals`，其中 `Technicals.PERatio` 为**持仓加权聚合** trailing P/E（官方文档确认口径；`QQQ.US` / `SMH.US` / `SOXX.US` 需逐 symbol 验证字段存在）
- **频率**：Technicals 日度刷新；ETF 持仓月度刷新；**无历史**（需自建存档）
- **价格**：Fundamentals Data Feed ~$60/月；All-In-One $99.99/月；免费档 20 calls/天（够做验证探针）
- **开通**：自助，注册即得 key；限额 100k calls/天（一次 fundamentals 请求计 10 calls）
- **定位**：如果用户想要的是"有合同、有 SLA 的付费源"而非 Robinhood 这类未文档化接口，选它；无 forward P/E

## 4. Zacks quote-feed —— 免费交叉验证

- **Endpoint**：`https://quote-feed.zacks.com/index?t=SMH`（`?t=QQQ` / `?t=SOXX` 同理）
- **字段**：`source.sungard.pe_ratio`（trailing）；实测 SMH `37.21`、QQQ `30.08`（updated: Sep 25, 2026 04:00 PM）；`pe_f1`（forward）**对 ETF 为空**
- **频率**：日度；免 key JSON；为 zacks.com 行情页供数
- **定位**：与 Robinhood 互相校验；口径不同是正常的

## 5. GuruFocus —— 可用但贵

- **API**：`https://api.gurufocus.com/data`，`GET /etf/{symbol}`（ETF profile + 关键统计，含 P/E；**仅 trailing，无 forward**）；无指数级（NDX/SOX）端点
- **价格**：API 需 Premium Plus（~$1,348/年，2 万次查询）或 Professional（~$2,398/年）；7 天免费试用，30 天退款；key 自助生成
- **定位**：EODHD 的更贵替代，无明显优势

## 6. FMP Ultimate —— DIY，不推荐

- 无聚合 ETF/index P/E 端点；只能 `etf/holdings` + 逐只 `ratios-ttm` 自算加权 trailing P/E
- ETF 持仓数据仅 **Ultimate $149/月** 可用；forward 需另查分析师预期
- 结论：为这一个指标付 2.5 倍 EODHD 的钱还自己写逻辑，不划算

## 7. 排除名单

| 供应商 | 原因 |
|---|---|
| Intrinio | 指数 tag 体系里没有 NDX/SOX 的 P/E tag；forward P/E 只有标普 500；$100–200+/月 |
| Twelve Data / Alpha Vantage / Tiingo / Polygon | 只有个股口径，无指数/ETF 聚合 P/E（DIY 成本高） |
| IEX Cloud | 2024-08-31 已关停 |
| Nasdaq Data Link | 目录里没有 NDX/SOX 的 P/E 数据集 |
| FactSet / Bloomberg / 标普 / Morningstar | 企业销售制，无自助购买，不适合个人项目 |
| stockanalysis.com | 旧 API 已死；页面有 P/E 但反爬且声明不提供程序化访问 |
| api.nasdaq.com | 无指数 P/E 端点；Nasdaq 官方 NDX 估值只有季度 PDF |
| Invesco/VanEck/iShares 官网 | 只有月度 factsheet，无日度 P/E |
| multpl / slickcharts / etfdb / Barchart / Morningstar 页面 | 无 NDX/SOX P/E，或只有季度旧数，或需登录/反爬 |

---

## Forward P/E 缺口说明

- **QQQ forward P/E**：免费无日度源（Zacks `pe_f1` 对 ETF 为空）。**唯一解是 Siblis 付费 API**（日度 forward，1990 年起）。
- **半导体 forward P/E（SMH/SOXX/SOX）**：付费免费都没有现成源。务实方案：daily trailing P/E（Robinhood）+ 月度 forward 序列缺失则页面注明；或向 Siblis Custom 询价加 SOX 覆盖（含 forward）。

## 建议的数据架构（付费意愿下的最优组合）

| 指标 | 数据源 | 频率 | 花费 |
|---|---|---|---|
| QQQ trailing P/E（headline） | Robinhood API | 日度 | 免费 |
| QQQ trailing P/E（10 年百分位） | worldperatio 月度序列（保留） | 月度 | 免费 |
| QQQ forward P/E | **Siblis Pro API** | 日度 | **$768/年** |
| SMH trailing P/E | Robinhood API | 日度 | 免费 |
| SOXX trailing P/E | Robinhood API（交叉：Zacks） | 日度 | 免费 |
| 半导体 forward P/E | 暂无；向 Siblis 询 Custom（SOX 覆盖） | — | 待报价 |

年花费：$768（仅 Siblis Pro）即可解决全部"太旧"问题；半导体 trailing P/E 用免费日度源已足够实时。

## 行动清单（需用户决策）

1. **发邮件给 sales@siblisresearch.com**：问两件事——(a) 公开 dashboard 展示的 redistribution 许可价格；(b) Custom 计划加 SOX 指数覆盖（含 forward P/E）的报价。拿到报价前不要下单 Pro。
2. **验证 Robinhood/Zacks 从 GitHub Actions 可达**（本沙盒可达 ≠ Actions runner 可达），跑一次探针即可。
3. 如用户想要"有合同"的半导体源而非 Robinhood 未文档化接口，再考虑 EODHD（$60/月），先用免费 20 calls/天探针验证 `SMH.US` 的 `PERatio` 字段。
4. 口径固定：一旦选定 headline 源（建议 Robinhood），trailing P/E 不再混用 Zacks/ETFDB 的数字；百分位继续用原月度序列。
