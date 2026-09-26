# 投资指标 Dashboard

为「中国房价判断」与「美国 QQQ 走势判断」提供实时、准确数据依据的个人 dashboard。
托管在 GitHub Pages，每日由 GitHub Actions 自动抓取最新数据并刷新。

## 指标清单（共 25 个）

### 市场情绪
| 指标 | 来源 | 更新频率 | 备注 |
|---|---|---|---|
| CNN 恐惧贪婪指数 | CNN Business（官方 JSON 接口） | 日度 | 0=极度恐惧，100=极度贪婪；含 9 个子指标；页面最顶部展示 |

### 美国 · 估值
| 指标 | 来源 | 更新频率 | 备注 |
|---|---|---|---|
| QQQ / Nasdaq-100 Trailing PE | Robinhood（日度 headline）＋ worldperatio（10 年百分位） | 日度 | 双口径已注明，不可跨口径比较绝对值 |
| QQQ / Nasdaq-100 Forward PE | Siblis Research | 月度 | 无免费长期历史，自建存档，满 12 个月启用百分位 |
| S&P 500 信息技术板块 Forward PE | Siblis Research | 月度 | 半导体前瞻估值的近似替代（SOXX 无稳定免费 forward 源）；自建存档 |
| S&P 500 Trailing PE | worldperatio | 月度 | 单一口径，10 年百分位 |
| SOXX Trailing P/E | Robinhood | 日度 | 日度口径；自 2026-09 起按月自建存档（旧 iShares 口径已作废） |

### 美国 · 股权供需
| 指标 | 来源 | 更新频率 | 备注 |
|---|---|---|---|
| 非金融企业净回购（TTM） | FRED · Z.1（`BOGZ1FU103164103Q`，季度 NSA） | 季度 | 净发行口径（发行−回购−并购注销），负值=净回购，取反得 TTM；与 S&P 500 总回购（毛值、含金融股）口径不同 |
| 美国 IPO 数量 | Jay Ritter（UF Warrington）IPO-Statistics Table 8 | 年度（每年 1 月更新上年） | 1960 年起；含当年融资额/首日平均涨幅；数量为情绪反向指标；另附当年 YTD 参考（Renaissance Capital，市值≥$5000万口径，与 Ritter 口径不同，仅作当年跟踪） |

## 一句话投资建议

页面最下方有一句每日自动生成的投资建议，由 `build_advice()` 按规则从指标合成：估值十年分位（Yardeni / Shiller 框架）、股债性价比（Fed model）、通胀 vs 2% 目标（美联储框架）、CNN 恐惧贪婪（逆向）、企业净回购（股权供需）。每条依据都列出"数据 → 结论"，生成逻辑透明可查。仅供参考，不构成投资建议。

### 美国 · 利率与通胀
| 指标 | 来源 | 更新频率 |
|---|---|---|
| 10 年期国债收益率（含 10 年百分位→贵/便宜判断） | FRED · DGS10 | 日度 |
| CPI 同比 | FRED · CPIAUCSL | 月度 |
| PCE 同比 | FRED · PCEPI | 月度 |

### 美国 · 流动性
| 指标 | 来源 | 更新频率 |
|---|---|---|
| 美联储总资产（QE/QT 阀门） | FRED · WALCL | 周度 |
| ON RRP 用量（过剩流动性水位） | FRED · RRPONTSYD | 日度 |
| 银行准备金余额 | FRED · WRESBAL | 周度 |
| 有效联邦基金利率 | FRED · DFF | 日度 |
| M2 货币供应 | FRED · M2SL | 月度 |

### 中国 · 宏观与地产（9 个）
| 指标 | 来源 | 说明 |
|---|---|---|
| 居民贷款占 GDP | BIS 总信贷统计（`stats.bis.org/api/v2`，`WS_TC/2.0`） | 国际口径，季度，滞后约半年；10 年百分位 |
| 居民人均可支配收入名义同比 | 国家统计局新版 API（`data.stats.gov.cn`） | 累计值自算同比；10 年百分位 |
| 居民人均可支配收入实际同比 | 国家统计局新版 API | 接口直接给实际增速；10 年百分位 |
| 一/二/三线城市新建商品住宅同比 | 统计局解读（当期官方加权口径）＋ 东方财富 70 城（历史研究口径：分线简单平均） | 10 年百分位 |
| 一/二/三线城市二手住宅同比 | 同上 | 10 年百分位 |

> **准确性说明**：全部使用免费公开数据源。FRED 优先走官方 API（`api.stlouisfed.org`，
> 需免费 key，见下方「FRED API key」），失败时回退无 key CSV。
> PE 类指标各家口径差异大，本项目对同一指标终身固定一家来源，并在页面标注方法论。
> **10 年百分位窗口为动态**：每次运行时按当天日期倒退 10 个日历年
> （如 2026-09-26 运行则窗口为 2016-09-26 起），不写死历史日期；抓取起始日期同样动态（当天倒退 11 年）。

## 本地运行

```bash
pip install -r fetch/requirements.txt
python3 fetch/run_all.py   # 生成 data/indicators.json
# 用浏览器打开 index.html 即可预览（需联网加载 Chart.js CDN）
```

## FRED API key（免费）

FRED 数据优先走官方 API（`api.stlouisfed.org`），需要一个免费 key：

1. 访问 <https://fredaccount.stlouisfed.org/apikeys> 注册并申请（免费，即时生效）。
2. GitHub 仓库 **Settings → Secrets and variables → Actions → New repository secret**，
   Name 填 `FRED_API_KEY`，Value 填申请到的 key。
3. 无 key 时自动回退无 key CSV 抓取（部分网络下可能被拦截，指标会沿用旧值并标记 stale）。

## 部署到 GitHub Pages

1. 在 GitHub 新建一个公开仓库（例如 `investment-dashboard`）。
2. 把本目录所有文件 push 到仓库的 `main` 分支：
   ```bash
   git init && git add . && git commit -m "init"
   git remote add origin git@github.com:<你的用户名>/investment-dashboard.git
   git push -u origin main
   ```
3. 仓库 **Settings → Pages**：Source 选择 `Deploy from a branch`，Branch 选择 `main` / `/ (root)`，保存。
4. 等待 1–2 分钟，访问 `https://<你的用户名>.github.io/investment-dashboard/`。
5. **Actions**：工作流 `.github/workflows/daily.yml` 会在每天美东时间 14:05 自动运行，
   抓取最新数据并提交到 `data/` 目录，页面随即更新。也可在 Actions 页面手动点
   `Run workflow` 立即触发一次。

## 文件结构

```
├── index.html                 # dashboard 页面（GitHub Pages 入口）
├── data/
│   ├── indicators.json        # 每日自动生成的指标数据
│   ├── _hist_qqq_forward_pe.json  # 自建：QQQ forward PE 月度存档
│   ├── _hist_it_forward_pe.json   # 自建：S&P 500 信息技术 forward PE 月度存档
│   ├── _hist_soxx_pe_rh.json      # 自建：SOXX PE（Robinhood 口径）月度存档
│   └── _hist_ipo.json             # 存档：Ritter IPO Table 8 解析结果（PDF 失败时兜底）
├── fetch/
│   ├── fetch_us.py            # 美国指标抓取
│   ├── fetch_cn.py            # 中国指标抓取（BIS/NBS/东财/统计局解读）
│   ├── compute.py             # 百分位 / 同比 / 信号计算
│   └── run_all.py             # 主流程（抓取→计算→写 JSON，失败自动沿用旧数据）
├── .github/workflows/daily.yml  # 每日自动更新
└── research/                  # 数据源调研报告
```

## 免责声明

本项目仅供个人研究参考，不构成投资建议。估值分位反映历史相对位置，不预测未来走势。
