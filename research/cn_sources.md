# 中国指标数据源调研报告（投资 Dashboard）

> 调研日期：2026-09-26
> 图例：****= 本次调研中真实请求验证；****= 官方/技术文档记载；****= 开源社区项目文档/issue 记载；****= 未能确认，需自行验证。
>
> 总体结论：三个中国指标都有**免费、无需付费 key 的官方/准官方程序化数据源**，但各有运维坑（见文末"跨指标运维建议"）。三个指标的历史序列都 ≥10 年，可支持 dashboard 计算 10 年 percentile。

---

## 指标一：中国居民贷款占 GDP 比例（household debt / GDP）

### 推荐数据源（按优先级）

#### 🥇 P1：BIS 总信贷统计（Total Credit Statistics）—— 国际标准口径

BIS 按季度发布"对家庭部门信贷占 GDP 比重"（Credit to households as % of GDP），含中国。

- **精确 endpoint**
- Base URL：`https://stats.bis.org/api/v2`
- Dataflow：`WS_TC`（"Total credit"），当前版本 **2.0**（注意：用 `/1.0/` 会 404）
- 数据请求模式（v2）：`https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0/{KEY}?startPeriod=2006-Q1&detail=dataonly&format=jsondata`
- 中国家庭部门候选完整 URL：
`https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0/Q.CN.H.A.M.770.A?startPeriod=2006-Q1&detail=dataonly&format=jsondata`——key 由 FRED 镜像系列 `QCNHAM770A` 的 source code `Q:CN:H:A:M:770:A` 转换而来；该 URL 实测返回 HTTP 200（路径有效），但精确 key 对应的序列数值尚未确认，**上线前必须用下方 python 方式验证**。
- **是否需要 key**：不需要，免费、无需注册。
- **历史深度**：中国家庭部门拆分序列自 **2006-Q1** 起（可支持 10 年 percentile）。
- **更新频率与发布滞后**：季度；滞后约 **5.5–6 个月**（BIS 方法文档 2026-06-15 更新对应最新数据 2025-Q4；FRED 镜像 2026-06-15 更新、最新值 2025-Q4，Q2 2025 值约 60.2%）。dashboard 每日刷新即可，实际每季度才变动一次——**需向用户明示该指标天然滞后半年**。
- **口径**：BIS "credit to households" = 住户及为住户服务的非营利机构的**贷款 + 债务证券**（含银行、非银、跨境债权人），口径大于国内"住户贷款"，是国际可比的 household debt/GDP 定义。
- **抓取方式（python 要点）**：
1. 必须发送 header `Accept: application/vnd.sdmx.data+json`（无版本号后缀；带 `;version=1.0` 会 406；普通 `application/json` 会被回退为 XML）；
2. 建议查询参数 `format=jsondata`、`detail=dataonly`；
3. 返回 SDMX-JSON：`data.structure.dimensions.series` 给出维度顺序，`data.dataSets[0].series` 的 key 如 `"0:0:0"` 是维度值索引——需按索引映射解析；
4. 无官方限流说明，GitHub Actions 每日 1 次请求完全合理；建议仓库保留静态快照兜底。
```python
import requests
url = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0/Q.CN.H.A.M.770.A"
r = requests.get(url, params={"startPeriod": "2024-Q1", "detail": "dataonly", "format": "jsondata"},
headers={"Accept": "application/vnd.sdmx.data+json"}, timeout=30)
print(r.status_code) # 期望 200 且返回含观测值的 SDMX-JSON
```

#### 🥈 P2：FRED 镜像（BIS 数据的官方转发）—— 交叉验证源

- 系列 ID：`QCNHAM770A`（"Total Credit to Households and NPISHs, Adjusted for Breaks, for China"，% of GDP，季度），区间 2006-Q1–2025-Q4。
- API：`https://api.stlouisfed.org/fred/series/observations?series_id=QCNHAM770A&api_key=YOUR_KEY&file_type=json`。
- 需要**免费 API key**（官网注册，120 次/分钟）；key 存 GitHub Secrets，Actions 定时抓取。滞后跟随 BIS。

### 中国人民银行官网评估 —— 不作主源

- 无直接等效指标。PBC 每月《金融统计数据报告》公布"住户贷款"余额/增量（文本新闻稿形式），每季度《金融机构贷款投向统计报告》有更细拆分。
- **官网无公开 API**，数据藏在 HTML 新闻稿中，抓取脆弱；且 PBC 住户贷款仅统计金融机构贷款，不含债券/跨境/非银信用，与 BIS 国际口径不可比；算"占 GDP 比"还需另配 GDP 数据。结论：仅作辅助参考。

### 不推荐的候选及原因

| 候选 | 原因 |
|---|---|
| IMF Global Debt Database | 年频、滞后大，无中国家庭债务/GDP 季度序列 |
| CEIC（有 China Household Debt: % of GDP，季度，最新约 60.4% @2025-Q3） | 收费订阅，无免费 API |
| Wind | 收费终端，无公开免费程序化接口 |
| Trading Economics | API 收费；二手转发，口径与更新透明度不如 BIS/FRED |
| IIF Global Debt Monitor | 仅季度 PDF 报告，无 API，无法自动化 |

---

## 指标二：中国居民收入增长率（全国居民人均可支配收入同比增速）

### ⚠️ 关键前置发现

**旧接口 `easyquery.htm?m=QueryData&dbcode=hgjd…` 已死亡**——国家统计局约 2026 年 5 月下线了该接口（社区项目 `mbk-dev/nbsc` 的 issue 与 README 均有记载）。旧的 `zb=A0301xx` 式指标代码已无法使用，**不要按旧 pattern 抓取**。

### 推荐数据源

#### 🥇 P1：国家统计局 data.stats.gov.cn 新版公开 API

- **权威性**：官方一手数据，与新闻发布会口径一致。
- **费用/认证**：免费，**无需 key、无需注册、无需 cookie**。
- **历史深度**：季度序列自 **2013-Q4** 起（与城乡一体化住户调查 2013 年启动吻合；可支持 10 年 percentile）；截至 2026-09-26 最新为 **2026-Q2**。
- **更新频率与发布滞后**：季度，季后约 **15–19 天**发布（2026-Q1 于 4 月 16 日、2026 上半年于 7 月 15 日、2025 全年于 1 月 19 日发布；2026-Q3 预计 2026 年 10 月 18 日左右发布）。

**精确接口 pattern（已实测）**：

```
POST https://data.stats.gov.cn/dg/website/publicrelease/web/external/stream/esData
Headers（必需）:
Content-Type: application/json
Referer: https://data.stats.gov.cn/dg/website/page.html # 否则可能被 WAF 拦截
User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36
```

请求体示例（全国居民人均可支配收入**实际**累计同比增速）：

```json
{
"cid": "ec2d57ed282f456e8d025aff035b4fad",
"indicatorIds": ["7abcbb6f7c844b669d43da985d3f6ff2"],
"daCatalogId": "",
"das": [{"text": "全国", "value": "000000000000"}],
"showType": "1",
"dts": ["201301SS-202602SS"],
"rootId": "a94b8b7365a94874968cabbe392cf679"
}
```

其中 `dts` 为季度区间格式 `YYYYQQSS-YYYYQQSS`；`rootId` 为季度数据根 UUID。

**已实测的目录/指标 UUID**（2026-09-26 当天从目录树真实抓取，非编造）：

| 用途 | cid（目录） | indicator_id（指标） | 说明 |
|---|---|---|---|
| 全国-可支配收入累计值（元） | `ec2d57ed282f456e8d025aff035b4fad` | `bb5699c5ad534b568cca7c946227225a` | 用于算**名义**同比 |
| 全国-可支配收入累计增长（%） | 同上 | `7abcbb6f7c844b669d43da985d3f6ff2` | **实际**同比增速，可直接用 |
| 城镇-累计值 / 累计增长 | `564537ad2e5049a6aee74c834b675748` | `e0b8d37be1b3445e8cbef405a28c5d95` / `cdb31eeca0824d2abfff388c114f1aaf` | 同上结构 |
| 农村-累计值 / 累计增长 | `62c5dd0cb4b74602b64e19e948460472` | `e80dbdec8c354aebaef94cb4d27a1ecb` / `48988f9103f74ba1bca8526b72dee54a` | 同上结构 |

同目录下还有中位数及四项收入来源（工资性/经营净/财产净/转移净）的累计值与累计增长指标，dashboard 如需细分可复用同 pattern。

**目录发现接口**（UUID 失效时重新发现用，已实测全链路走通，无需浏览器）：

```
GET.../new/queryIndexTreeAsync?code=2 → 季度数据根 (a94b8b7365a94874968cabbe392cf679)
GET.../new/queryIndexTreeAsync?pid=<父UUID>&code=2 → 子目录（季度数据→人民生活→全国居民人均收入情况）
GET.../new/queryIndicatorsByCid?cid=<叶UUID>&dt=&name= → 指标列表
```

code 对照：`1`=全国月度，`2`=全国季度，`3`=全国年度，`4/5/6`=分省月/季/年，`7`=主要城市月度价格，`8`=主要城市年度，`9`=港澳台月度。

返回结构示例：`{"state":20000,"success":true,"data":[{"code":"202602SS","name":"2026年第二季度","values":[{..."value":"4.2","du_name":"%",...}]}]}` —— `value` 为字符串需转浮点；`202602SS` = 2026 年第二季度。

**⚠️ 必须注意的口径**：
- DB 中的"累计增长 (%)"是**实际增速（扣除价格因素）**，不是名义增速（2026-Q1 DB 值 4.0 = 官方实际 4.0%，官方名义为 4.9%；2026-Q2 DB 值 4.2 = 官方实际 4.2%，名义 5.2%）。
- **名义增速需用"累计值（元）"序列自行计算同比**：如 `12782/12179−1=4.95%≈4.9%`（2026-Q1）、`22981/21840−1=5.22%≈5.2%`（2026 上半年），与发布会名义值吻合。
- Dashboard 建议：名义与实际**两者都展示**最严谨。

**Python 抓取示例**（实测延迟约 1–10 秒/请求）：

```python
import requests
API = "https://data.stats.gov.cn/dg/website/publicrelease/web/external/stream/esData"
H = {"Content-Type": "application/json",
"Referer": "https://data.stats.gov.cn/dg/website/page.html",
"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}
body = {"cid": "ec2d57ed282f456e8d025aff035b4fad",
"indicatorIds": ["7abcbb6f7c844b669d43da985d3f6ff2"], # 实际增速；名义用 bb5699c5ad534b568cca7c946227225a
"daCatalogId": "", "das": [{"text": "全国", "value": "000000000000"}],
"showType": "1", "dts": ["201301SS-202602SS"],
"rootId": "a94b8b7365a94874968cabbe392cf679"}
r = requests.post(API, json=body, headers=H, timeout=30)
assert r.json()["state"] == 20000
series = [(p["code"], p["name"], p["values"][0]["value"]) for p in r.json()["data"]]
```

#### 🥈 P2：统计局官网新闻稿（交叉校验）

`stats.gov.cn/sj/zxfb` 每季度发布文字版，可人工/爬虫核对 API 数值。CEIC 中国 Premium 库 Table CN.HD 有完全对应序列但**付费**，仅适合有预算的校验场景。

### 运维风险提示（每日自动刷新必须处理）

1. **UUID 非官方文档，随时可能失效**：NBS 在 2026-05-27 起两周内两次改名数据端点（`easyquery.htm` 死亡 → `getEsDataByCidAndDt` → `stream/esData`），目录 UUID 曾幸存但无保证。应对：CI 先校验 `state==20000` 且数据非空；失败则按上文目录接口自动重发现（纯 requests 可走通）。
2. **IP 地理封锁风险**：NBS 会丢弃美国数据中心 IP 的请求。**GitHub Actions 默认 runner 是美国 Azure IP，可能被静默丢弃**。应对：加超时+重试+失败告警；或把抓取任务放到非美国出口的 runner/代理后执行；失败时保留昨日缓存而非写空值。
3. **数据修订**：NBS 偶尔修订历史值，建议每次全量重拉而非仅追加。

### 不推荐的候选及原因

| 候选 | 原因 |
|---|---|
| 旧 `easyquery.htm`（`dbcode=hgjd`） | HTTP 403 已下线；旧 zb 代码无验证意义 |
| FRED | 免费（需 key）但 932 个中国序列来自 OECD/IMF/世行/PWT/BIS，**无"中国住户可支配收入"季度序列** |
| OECD Data Explorer API | 免费 SDMX API，但季度住户可支配收入数据流（DF_QNA_INC_SAV）仅覆盖 11 国，**不含中国** |
| 世界银行 WDI API | 免费免 key 可用，但**只有年度**数据，且无中国住户可支配收入指标 |
| Trading Economics | 无免费层（`guest:guest` 已于 2026-07 停用），标准版 $149/月起 |
| CEIC / Wind / Choice | 有精确对应序列但均为付费 |

---

## 指标三：中国房价分一二三线城市增长率（70 城商品住宅销售价格指数）

### ⚠️ 关键结构性发现

**一线/二线/三线城市的聚合环比、同比指数，统计局只在每月"解读"文字中给出，不存在于任何 70 城表格或 API 的城市级记录中**。因此 dashboard 必须采用**"城市级走接口 + 分线聚合走解读文本解析"双轨制**。

### 推荐数据源（按优先级）

#### 🥇 P1：东方财富 `RPT_ECONOMY_HOUSE_PRICE`

免费、无需 key、单接口全量返回 70 城新建/二手住宅环比+同比指数，2011-01 至今，**数值与国家统计局官方发布完全一致**。

- **接口 pattern（GET，无鉴权）**：
```
https://datacenter-web.eastmoney.com/api/data/v1/get
?reportName=RPT_ECONOMY_HOUSE_PRICE
&columns=CITY,REPORT_DATE,FIRST_COMHOUSE_SAME,FIRST_COMHOUSE_SEQUENTIAL,SECOND_HOUSE_SAME,SECOND_HOUSE_SEQUENTIAL
&filter=(REPORT_DATE='2026-08-01 00:00:00')
&pageNumber=1&pageSize=200
&sortColumns=REPORT_DATE&sortTypes=-1
```
- `filter` 支持 `(CITY="北京")`（城市名必须用**双引号**，单引号实测报错"参数预处理错误"）、`(REPORT_DATE>='2026-01-01 00:00:00')` 等日期区间。
- 返回 JSON `result.data[]`，字段语义：

| 字段 | 含义 |
|---|---|
| `CITY` | 城市名（70 个大中城市） |
| `REPORT_DATE` | 数据月份（每月 1 日 00:00:00） |
| `FIRST_COMHOUSE_SAME` | 新建商品住宅**同比**指数（上年同月=100） |
| `FIRST_COMHOUSE_SEQUENTIAL` | 新建商品住宅**环比**指数（上月=100） |
| `SECOND_HOUSE_SAME` | 二手住宅同比指数 |
| `SECOND_HOUSE_SEQUENTIAL` | 二手住宅环比指数 |
- **是否需要 key**：不需要，公开接口。
- **历史深度**：2011-01 ~ 2026-08，共 188 个月；每月恰好 70 行，无分线聚合行。可支持 10 年 percentile。
- **准确性**：北京 2026-08 新建环比 99.8（官方 −0.2%）、二手环比 99.9（官方 −0.1%）✅；上海 2026-08 新建同比 103.0（官方 +3.0%）、新建环比 100.4（官方 +0.4%）、二手环比 100.3（官方 +0.3%）✅。
- **更新频率/滞后**：月度，滞后约 15 天（统计局每月 15 日左右发布上月数据，偶延至 16–17 日；2026 年 8 月数据 → 2026-09-15 发布）。东财与统计局同步更新。建议 cron 定在**每月 16 日拉取、17 日补拉**，以"当月 70 条记录、城市覆盖齐全"做完整性校验。
- **抓取要点**：加浏览器 UA；GitHub Actions 每日 cron 做轻量轮询（`filter=(REPORT_DATE>='YYYY-MM-01')` 只看条数变化）；建议本地缓存 CSV 做 diff，避免重复写入。
- **已知局限**：2023 年起统计局停发定基指数，定基字段返回 null；跨基期长期趋势需用环比连乘重建（需注明为"研究口径构造"）。

#### 🥈 P2：国家统计局月度"解读"页文本解析

- 一线/二线/三线城市新建+二手住宅的**环比/同比涨跌幅**只出现在统计局每月解读文字中（例："8 月份，一线城市新建商品住宅销售价格环比上涨 0.1%……二线城市环比下降 0.1%……三线城市环比下降 0.2%"）。
- **抓取方式**：每月从统计局最新发布页（`https://www.stats.gov.cn/sj/zxfb/` 列表）找到「70 个大中城市商品住宅销售价格变动情况」当月条目，抓正文后用正则提取固定句式。社区已有成熟先例：[hugohe3/70cityprice](https://github.com/hugohe3/70cityprice) 项目即采用"解析官方发布页"路线（文档注明"每月 15–17 日发布上一月数据；URL 里的月份是发布月，数据月份要减 1"）。
- **一二三线划分（官方口径，来自 2026 年 1 月官方发布 PDF）**：一线 = 北京、上海、广州、深圳（4 城）；二线 = 天津、石家庄、太原、呼和浩特、沈阳、大连、长春、哈尔滨、南京、杭州、宁波、合肥、福州、厦门、南昌、济南、青岛、郑州、武汉、长沙、南宁、海口、重庆、成都、贵阳、昆明、西安、兰州、西宁、银川、乌鲁木齐（31 城）；三线 = 其余 35 城。**官方聚合为加权计算，不可用 70 城简单平均替代，必须从解读文字取数**。
- 该页同时是城市级数据的"官方校验源"（可用东财城市值与页面表格抽查比对）。

#### 🥉 P3：国家统计局 easyquery / 新版 API V2.0（兜底备选）

- **旧版 easyquery（`data.stats.gov.cn/easyquery.htm?m=QueryData&dbcode=hgyd…`）**：从境外出口 IP 直连被 WAF 拦截，返回 `403 Forbidden / reason:UrlACL`（加 Referer、换 UA 均无效）。据社区记载境内服务器可通行，但反爬强、可靠性存疑，**不建议作为 GitHub Actions（境外 runner）的主链路**。
- **新版 API V2.0（`https://data.stats.gov.cn/dg/website/publicrelease/web/external`）**：据社区记载流程为 `POST /new/queryIndexTreeAsync` 取分类树 → `POST /new/queryIndicatorsByCid` 取指标 → `POST /getEsDataByCidAndDt` 取数；本次实测 `queryIndexTreeAsync` 未走通（返回"服务异常"前端错误页）。**未实测成功**。
- **指标代码（如 A0603 开头系列）：待验证⚠️**——搜索 GitHub/博客未找到任何可交叉验证的 70 城房价指数 easyquery `zb.valuecode` 公开记录，**不编造**。验证方法：在境内网络用浏览器打开 `data.stats.gov.cn` 月度库查询页，F12 → Network，手动点选"商品住宅销售价格指数"指标后复制 `QueryData` 请求的 `wds` 参数（`wdcode:"zb"` 对应的 `valuecode` 即为真实指标代码）。注意 `dbcode=hgyd` 本身也只见于社区文档记载，未经实测。
- 注：本报告指标二（居民收入）已实测打通的**新版 `stream/esData` UUID 接口**同样适用于月度库（code=1 全国月度），可按相同目录发现流程自行钻取房价指数的 cid/indicatorId——这是比旧 easyquery 更可行的 NBS 直连路线。

#### P4：中指研究院官网（补充绝对价格/租金，非指数主源）

- **可抓取性**：`https://www.cih-index.com/data/index/{newHouse|esfHouse|rentIndex}.html` 本次 curl 返回 HTTP 200 且含 `window.__INITIAL_STATE__` 标记；据社区实测记载（2026-08）：页面 SSR 内嵌 JSON，无登录、无验证码，含 100 城新建/二手**样本均价（元/㎡）**+环比/同比、50 城**平均租金（元/㎡·月）**+环比/同比，以及 12 个月全国趋势。**无正式 JSON API**。
- **定位**：只能做"绝对价格/租金"补充层（例如展示租金收益率），**不提供 NBS 一二三线口径指数**，不能替代 P1/P2。
- **风险**：SSR 结构依赖官网改版（需定期回归验证）；百城均价为"样本均价"口径，展示须注明；仅 12 个月趋势。

### 口径与历史变更点（dashboard 必须标注）

| 时间 | 变更 | 依据 |
|---|---|---|
| 2011-01 | 现行口径起点：按"新建住宅/二手住宅"分类发布环比+同比（东财数据亦始于 2011-01） | 已实测 |
| 2011–2015 / 2016–2020 / 2021–2022 | 定基指数基期五年一轮换（2010=100 → 2015=100 → 2020=100） | 社区记载 |
| 2023 年起 | **停发定基指数**，仅发布环比/同比 | 社区记载 + 实测 |
| 2026-01 起 | 以 **2025 年为新一轮对比基期**，各城市基本分类权数调整；官方测算对同比指数影响平均约 0.03 个百分点 | 2026 年 1 月官方发布 PDF 附注 |

建议 dashboard 时间序列统一从 2011-01 起；如需长期趋势，用环比连乘重建并明确标注方法。

### 不推荐的候选及原因

| 候选 | 原因 |
|---|---|
| 贝壳/链家、安居客爬虫 | 反爬极严、非官方口径、稳定性低 |
| 禧泰数据 creprice.cn 公开页 | 公开页面有**验证码反爬**，只能走商业 API |
| 房天下 API | 商业，免费仅 100 次/天，且为小区级口径 |
| 易源数据 API | 有免费层但数据质量存疑 |
| 地方数据开放平台 | 各城市接口不统一、口径不一致 |
| NBS easyquery 直连（境外） | 本次实测被 WAF 403 拦截；仅作境内兜底 |

---

## 跨指标运维建议（GitHub Pages + Actions 每日刷新）

1. **刷新策略**：每日 cron 做轻量"有无新数据"检查即可，实际抓取按各指标发布节奏触发——BIS 季度（滞后半年）、居民收入季度（季后 ~15–19 天）、房价月度（每月 16 日拉取、17–18 日补拉）。
2. **IP 地理封锁是最大风险**：NBS 新版 API 已观测到丢弃美国数据中心 IP（GitHub Actions 默认 runner 为美国 Azure IP）；东财接口本次可从境外直连，但同样建议生产环境回归验证。应对：超时+重试+失败告警；考虑非美国出口 runner/代理；**失败时保留昨日缓存而非写空值**。
3. **完整性校验**：每次更新后校验记录数与连续性（房价当月 70 城齐全、BIS 序列非空、NBS `state==20000`），抽查 2–3 个城市与统计局发布页表格比对。
4. **静态快照兜底**：仓库中保留各指标最新全量 CSV 快照，API 不可用时 dashboard 降级展示快照并标注数据日期。
5. **向用户明示滞后与口径**：BIS 家庭债务/GDP 滞后约半年属正常；NBS"累计增长"为实际增速、名义需自算；房价分线聚合来自官方解读文本（加权口径，不可简单平均）；2023 年起无定基指数、长期趋势为环比连乘构造。
6. **UUID/接口变更监控**：NBS 在 2026 年 5 月两周内两次改名端点；建议 CI 中对 NBS 接口做"目录树可发现性"探针，UUID 失效时按本报告目录发现流程自动重发现（纯 requests 可走通，约 5 分钟可手工完成）。

---

## 待验证事项清单（上线前）

- [] BIS `WS_TC/2.0` 下中国家庭信贷/GDP 精确 series key 的数值验证（候选 `Q.CN.H.A.M.770.A`，需带 `Accept: application/vnd.sdmx.data+json` header 实测）
- [] NBS 70 城房价指数在新版 `stream/esData` 接口中的 cid/indicatorId（按 code=1 全国月度目录树钻取；旧 easyquery zb 代码已死，不必再找）
- [] GitHub Actions 美国 runner 对 NBS 新版 API / 东财接口 / BIS API 的连通性回归验证
- [] FRED API key 申请（免费）作为 BIS 交叉验证源
