# macro-watch · 金铜宏观观测系统

长期跟踪一套宏观分析框架(出处:公众号「市场评论和展望」《鸽派的Warsh,鹰派的市场》),
用于观察**国际金价**与**沪铜**。零后端、零构建、零第三方依赖:
一个 git 仓库同时是数据库(平文本 CSV/JSON + git 历史)、采集器(Python 标准库)和网站(静态页 + vendored ECharts)。

## 框架摘要(系统编码的逻辑)

- **联储反应函数**:10Y 盈亏平衡通胀预期 <2.5% 不鹰派;Trimmed Mean PCE 回到 2.0% 或失业率明显走高(Sahm 规则量化)才降息;中间=按兵不动区。
- **黄金双杀组合**:通胀预期回落 + 实际利率走高 → 黄金最不利,一票否决。
- **AI Capex 主线**:决定长端利率与纳指;**纳指破前高 = 追铜信号**。
- **三情景**:①地缘稳定+AI新叙事(利率高位,金不利铜可追)②地缘稳定+Capex放缓(降息,金铜双受益)③地缘不稳(油价急涨,滞胀)。
- **黄金五条件**:价格 vs EMA200、ETF 流向、CFTC 净多头 5 年分位(30–60% 回暖=看多)、COMEX OI 见底反弹、央行购金力度。
- **沪铜**:95000–110000 区间(95000 下游点价支撑 / 105000+ 压力);非宏观扰动的下跌是买点(用 HY 利差和 WTI 区分);COPX 领先铜价。

每个信号的**精确计算定义**在仪表盘"方法论"区和 `pipeline/signals.py` 内注释,全部阈值集中在
`config/thresholds.json` —— 观点演进时改配置即可,不用改代码。

## 运行

**云端(主运行方式)**:GitHub Actions 每个交易日两班(15:35 北京时间抓沪铜收盘、22:30 UTC 抓美盘收盘,
周五顺带接住 COT 周报),采集 → 算信号 → commit 回仓库 → GitHub Pages 自动重发布。

**本地**:

```bash
./scripts/run_local.sh          # 全量采集 + 信号 + http://localhost:8000 预览
SKIP_SOURCES=fred,yahoo ./scripts/run_local.sh   # 跳过慢源,只调前端
```

无需安装任何依赖(Python 3.10+ 标准库)。
**国内网络注意**:FRED/Yahoo 等海外源可能被间歇性干扰(连接建立后"滴流"挂死)。采集器有三层防护
(总时限死线 → curl 兜底 → 滴流后 curl 优先),但若持续失败,给终端挂上代理即可:
`export https_proxy=http://127.0.0.1:<端口>`(urllib 与 curl 都会自动使用)。云端 Actions 无此问题。

## 数据源与口径

| 数据 | 来源 | 频率 | 策略 |
|---|---|---|---|
| T10YIE/DFII10/TrimmedPCE/DGS2/10/30/T10Y2Y/UNRATE/FEDFUNDS/HY利差/WTI | FRED 免key CSV | 日/月 | 全量覆盖(必须单序列逐个请求,合并请求会返回 zip) |
| 沪铜主力 CU0 日K(2005至今,含持仓量)+ 实时快照 | 新浪期货 | 日 | 全量覆盖;实时价只展示不入库 |
| 国际金价 **GC=F**、COPX、GLD、^IXIC | Yahoo chart API | 日 | 首跑 range=max 回填,之后 range=1y 增量合并、新值覆盖(XAUUSD=X 不可用,金价口径为 COMEX 主力) |
| 黄金/COMEX铜 净多头与 OI | CFTC Socrata(legacy futures-only) | 周 | 增量追加;**口径**:noncommercial 净多头作 managed money 代理 |
| SPDR GLD 官方持仓吨位 | spdrgoldshares.com | 日 | 端点 2026-07 起返回 PDF(失效),采集器保留探测+三重校验,恢复即自动接管 |
| 黄金 ETF 月度流量、央行购金、AI Capex | 人工录入(见下) | 月/季 | `data/manual/*.json` |

## 人工维护(每月 ~2 分钟 + 每季 ~10 分钟)

三个文件都可在 GitHub 网页编辑器直接改,`_instructions` 字段写明去哪抄哪个数;
schema 有校验,改坏了只会让对应信号变灰,不会炸流水线:

1. **`data/manual/gold_etf_flows.json`**(每月 10 日前):WGC goldhub → Gold ETF flows 月报 → 全球持仓(吨)+ 当月净流量(吨)。
2. **`data/manual/central_bank_gold.json`**(每季,GDT 季报发布后):WGC Gold Demand Trends → Central banks 净购金(吨)。
3. **`data/manual/ai_capex.json`**(每季财报后):四家 10-Q 现金流量表 capex(十亿美元),按日历季度;MSFT 财年错位(FY Q3=日历 Q1);未发布的公司先填 null。
   - **回填清单**:2025Q1–Q4 四家数据补齐后,YoY 与"放缓确认"信号才会点亮。

## 可靠性设计(为什么敢长期用)

- **单源失败隔离**:任何源挂了不影响其他源;失败只体现为 status 红标 + 页面红灯 + 对应信号转灰(**宁灰勿错**)。
- **行数护栏**:全量覆盖前校验新行数 ≥ 旧行数×0.95,反爬/截断的坏响应永远不会覆盖好数据。
- **原子写**:tmp + rename,中途被杀不留半截文件。
- **自愈**:FRED/新浪是全历史响应,任何历史修正自动带回;COT 删掉 CSV 下次自动全量重拉;Yahoo 增量合并时新值覆盖旧值。
- **出事能知道**:CI 末步 `check_status` 在有源失败/超龄时让 workflow 变红,GitHub 对连续失败的定时 workflow 会发邮件。
- **数据可审计**:全部平文本 + git 历史,任何一天的信号都能回溯到当天的原始数据。

## 故障排查

| 症状 | 处置 |
|---|---|
| COT 数据疑似缺段/错乱 | 删除 `data/cot/*.csv`,下次运行自动全量重拉 |
| Yahoo 持续 429/失败 | `pipeline/yahoo.py` 里把 `query1` 换成 `query2.finance.yahoo.com`(备用域名) |
| 定时任务停摆(长假后) | GitHub 对 60 天无 commit 的仓库暂停 schedule;本仓库交易日天天有 commit 天然免疫;若真停了,Actions 页面手动 Run workflow 一次即恢复 |
| GLD 自动源恢复了想确认 | status 表看 `auto:gld_holdings` 变绿即已自动接管,ETF 信号自动切回日频吨位 |
| 信号大面积变灰 | 先看页面"数据新鲜度"表哪个源红了;本地跑 `python3 -m pipeline.check_status` 看摘要 |
| 想调整阈值(如沪铜区间上移) | 只改 `config/thresholds.json`,下次运行生效,前端方法论区同步显示新值 |

## 目录结构

```
index.html assets/          # 仪表盘(ECharts vendored,零 CDN)
config/thresholds.json      # 全部信号阈值(文章框架数字集中地)
data/fred|market|cot|auto/  # 自动采集数据(CSV)
data/manual/                # 人工月度/季度录入(JSON)
data/status.json            # 每源健康状态   data/signals.json  # 信号计算结果
pipeline/                   # 采集+信号(纯标准库);run_all 为唯一入口
.github/workflows/collect.yml  # 两班 cron + 手动触发
scripts/run_local.sh        # 本地一键
```

> 数据仅供个人研究参考,不构成投资建议。
