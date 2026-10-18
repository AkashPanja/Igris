# Autonomous Multi-Agent AI Trading System for Indian Markets: Architecture, Shared Memory and Human Oversight

Oct 18, 2026 · @Akash Panja

## Abstract

A hybrid design, in which deterministic code owns risk and execution while language-model agents research and rank, is the most defensible way for a retail trader to automate intraday and F&O trading in India in 2026. This paper specifies a team of cooperating agents that read and write one shared database on a Synology NAS. The user can inspect and edit that memory on a website and change the trading rules by talking to a main chat agent.

The user supplies a personal watchlist. The agents also research the wider market, news, sentiment and the international events that move Indian equities, and propose trades tagged by origin. Every proposal runs in paper-trading mode by default with realistic costs, and live mode can be enabled only from a website button. We justify the design from SEBI's retail algo framework, retail F&O loss data and recent research on LLM trading agents, and we set forward-testing criteria that must be met before real capital is used.

## 1. Introduction

The goal is an agent that can propose and, once the user allows it, place intraday and F&O trades without the user watching every tick, while staying inside limits the user controls. Three requirements shape everything that follows.

- **Two sources of ideas.** The user shares a personal list of stocks. The agents also run their own research, because a personal list will not always contain the day's liquid or news-driven opportunities.
- **Transparent shared memory.** Every agent reads and writes the same store, and the user can see and edit it.
- **Conversational control.** The user changes risk values and behaviour by talking to a main agent, with the same rules also editable on the website.

The contributions of this paper are: (1) a layered architecture that separates LLM judgement from deterministic risk and execution code; (2) a shared-memory schema that doubles as the user's dashboard; (3) a governance model for changing rules by chat without weakening safety; (4) a research pipeline that blends market data, news, sentiment and international events; and (5) an evaluation plan with explicit go-live criteria.

The system is designed for personal use by one trader. Offering it to others would change its regulatory status (Section 2).

## 2. Regulatory and market context in India

SEBI's retail algo framework has applied in full since 1 April 2026, and a personal, transparent, low-frequency system running from a registered static IP sits inside it ([Antsheel summary of SEBI circulars](https://antsheel.com/blog/sebi-retail-algo-trading-rules-2026-india/)). The market data below explains why the risk layer matters more than the model.

### 2.1 What the framework requires

- **Static IP and session rules.** [Fyers' notice](https://fyers.in/notice-board/new-sebi-framework-for-retail-algo-trading-from-april-01-2026) says orders are accepted only from a registered app ID mapped to a whitelisted static IP. It also requires 2FA once every trading day, a cap of 10 orders per second, and automatic conversion of market orders to MPP orders.
- **IP changes are limited.** A trader can register one primary and one backup static IP, and changes are allowed about once a week ([Antsheel](https://antsheel.com/blog/sebi-retail-algo-trading-rules-2026-india/)).
- **Traceability.** Algo orders carry an exchange-recognised strategy ID, and the broker is the party responsible to the exchange. Algos below 10 orders per second do not need separate exchange registration, though broker checks still apply (same source).
- **Personal use.** The rules permit personal use of your own algorithm, extended to a spouse, dependent children and dependent parents ([Tradejini](https://www.tradejini.com/blogs/what-sebis-new-algo-trading-rules-mean-for-you)).
- **Black-box strategies offered to others** need additional registration, reported by industry guides as a SEBI Research Analyst licence ([Dozen Diamonds](https://www.dozendiamonds.com/retail-algo-trading-sebi-new-rules/)).

Open question: whether editing an LLM prompt counts as a material change to a registered strategy. We found no SEBI text on this, so it should be put to the broker in writing.

**Design consequences.** The NAS must keep its public IP stable, the agents stay idle until the daily 2FA login succeeds, an order rate limiter sits in front of the executor, and every order is logged with its strategy ID.

### 2.2 The base rates

- SEBI's July 2025 study found 91% of individual F&O traders lost money in FY25. Net losses widened 41% to ₹1,05,603 crore, from ₹74,812 crore in FY24 ([summary of SEBI studies](https://imrawal.com/Website/articles/sebi-fo-study-why-retail-traders-lose.html)).
- SEBI's 2024 study of equity-cash intraday trading found 71% of individuals made a net loss in FY23 ([Business Standard](https://www.business-standard.com/amp/markets/news/7-in-10-intraday-traders-in-equity-cash-suffered-losses-in-fy23-sebi-study-124072400975_1.html)).
- From 1 April 2026, STT on futures rose from 0.02% to 0.05%, and on options premium from 0.1% to 0.15% ([Outlook Money](https://www.outlookmoney.com/invest/stt-hike-from-april-1-2026-budget-what-it-means-for-futures-and-options-traders)). Strategies that were marginally profitable before may now lose money after costs.

### 2.3 Broker MCP options

| Broker MCP | Order placement | Notes |
| --- | --- | --- |
| [Fyers MCP](https://fyers.in/mcp) | Yes: orders, GTT, baskets, square-off where enabled | Endpoint mcp.fyers.in |
| [Groww MCP](https://dev.to/govind_sisara/indian-stock-market-mcp-the-best-mcp-servers-for-nse-bse-data-2026-p28) | Yes; sell orders need DDPI | Hosted at mcp.groww.in |
| [Zerodha Kite MCP](https://zerodha.com/z-connect/featured/connect-your-zerodha-account-to-ai-assistants-with-kite-mcp) | No, except GTT | Market data and portfolio analysis |

The Groww and Kite rows come from third-party and Zerodha-published descriptions that may have changed. Confirm each broker's current documentation before building on it.

## 3. Evidence on LLM trading agents

The research record does not support trusting an LLM with unconstrained trading decisions, which is why this system confines the LLM to research and ranking.

- **Reported gains are fragile.** One 2026 position paper argues that reported alpha from end-to-end LLM trading systems should not count as evidence of deployable ability until it survives structural validity checks. It cites work finding that most LLM agents struggle to beat passive buy-and-hold once temporal leakage and execution realism are controlled ([arXiv 2605.16895](https://arxiv.org/pdf/2605.16895)).
- **Backtests can leak.** Even when code feeds only information visible at the time, the model's weights may already contain post-event news and price-path summaries (same paper). Forward testing in live markets is therefore the only trustworthy evaluation.
- **Live results are noisy.** Live benchmarks remove look-ahead but cannot be replicated, and LLMs can produce very different trading actions across runs even with deterministic decoding ([AlphaForgeBench](https://arxiv.org/pdf/2602.18481)).
- **General ability does not predict trading skill.** A 50-day live evaluation of 21 LLMs found a weak correlation between general language ability and trading success ([LiveTradeBench summary](https://www.alphaxiv.org/abs/2511.03628)).
- **No consistent winner.** A two-month live multi-market benchmark found no single LLM or agent consistently outperformed the others across all assets ([Agent Market Arena](https://www.researchgate.net/publication/396459334_When_Agents_Trade_Live_Multi-Market_Trading_Benchmark_for_LLM_Agents)).
- **Structure helps.** In one comparison, role-playing agents were unstable across backbone models, while structured, factor-centric workflows were more consistent ([AlphaCrafter](https://arxiv.org/pdf/2605.05580)).

**Implications for the design.** First, keep the LLM's job narrow and its output structured. Second, make every number that matters (stop, size, caps) come from code. Third, judge the system only on forward paper results that include costs. Fourth, log every LLM input and output so run-to-run variation can be measured rather than guessed.

## 4. System architecture

The system has four layers: data sources, research agents, shared memory, and decision and execution. Only four agents call a language model, and every agent that touches orders is plain code.

&#91;embedded content: system architecture · 4 layers, 4 model-using agents\]

Data flows down from the sources through the research agents into shared memory, then left to right through the Analyst, the risk checks, execution and monitoring. The website, the main chat agent and the Reporter reach the same memory from the side.

### 4.1 Agent roster

| Agent | Uses a model? | Job |
| --- | --- | --- |
| Scout | No | Scans the user's watchlist and the wider market (gainers, losers, volume spikes, option-chain activity) and tags signals |
| News and Sentiment | Yes, small model first | Clusters headlines, separates facts from inference, scores sentiment per stock and sector |
| Global Macro | Yes | Writes a pre-market note on overseas developments and their likely sector impact |
| Analyst | Yes, stronger model | Ranks candidates and drafts structured trade proposals |
| Risk Manager | No | Checks each proposal against the rules, sets size and stop, vetoes breaches |
| Executor | No | Simulates fills in paper mode; sends previewed orders to the broker in live mode |
| Monitor | No | Watches live prices and exits at the stop or target |
| Reporter | No | Computes net P&L per trade and per day and stores structured lessons, such as hit rate by source and sector |
| Main chat agent | Yes | Talks to the user, answers from memory, and changes rules only through validated tools |

### 4.2 Why the split

Anything that must be exact, such as position size, stops, caps and order handling, is code that behaves the same on every run. Models handle the judgement over text and context that code cannot do well. This follows the evidence in Section 3, where structured workflows were steadier than free-form role-playing agents.

## 5. Shared memory the user can see

The agents never talk to each other directly. They communicate through one database on the NAS (SQLite or Postgres), and the website renders the same tables, so what the agents know is exactly what the user can see and edit.

This has three advantages over agent-to-agent chat. Rows are structured, so an agent reads only the few it needs instead of a long transcript. Every row is auditable. And a bad or hallucinated entry can be found and deleted by the user.

### 5.1 Schema

| Table | Written by | Read by | Contents |
| --- | --- | --- | --- |
| rules | User only (website or chat tool) | All agents | Risk per trade, max open positions, daily loss limit, allowed instruments, paper or live mode |
| watchlist | User | Scout, Analyst | The user's stocks, optional notes, source tag "user" |
| signals | Scout, News and Sentiment, Global Macro | Analyst | Candidate symbol, catalyst, score, source tag ("user" or "agent"), timestamp |
| research\_notes | News and Sentiment, Global Macro | Analyst, main chat | Short clustered summaries with source links, sentiment score and an expiry time |
| proposals | Analyst | Risk Manager, Executor, user | Entry, stop, target, quantity, rationale, confidence |
| trades | Executor, Monitor | Reporter, user | Paper or live fills, exits, costs, realised P&L |
| lessons | Reporter | Analyst, main chat | Short post-trade findings, summarised on a rolling basis |
| audit\_log | System | User | Every rule change, order, veto and mode switch, with actor and time |

### 5.2 Visibility and control

The website has one page per table. The rules page is an editable form. The research and proposals pages show each row with its source links and which agent wrote it, so the user can see why a trade was proposed. The user can pin, edit or delete research notes and lessons, and the agents treat a deleted row as gone.

The main chat agent can answer questions such as "what do you know about this stock?" by reading the same tables, and it can change user-owned rows only through validated tools (Section 6).

### 5.3 Memory hygiene

- **Expiry.** Intraday research notes expire at market close, so stale news cannot drive tomorrow's trades.
- **Rolling summaries.** Old lessons are compressed into a short standing summary, which keeps prompts small.
- **Provenance.** Every row stores the agent, timestamp and source URLs.
- **Untrusted text.** News content is stored as data and never as instructions (Section 9).
- **Write permissions.** Each agent can write only its own tables. The Risk Manager, Executor and Monitor are plain code and cannot be steered by text in memory.

## 6. Conversational control and rule governance

The website form and the main chat agent write to the same rules table, so both paths pass through the same validation and neither can bypass the safety limits.

### 6.1 How a chat change works

1. The user types a request, for example "reduce risk per trade to 0.5%".
2. The main agent calls an `update_rule` tool in preview mode. Code checks the value against the hard caps.
3. The agent shows old value and new value and asks the user to confirm.
4. On confirmation the value is written and an audit\_log entry records who, what and when.
5. The change applies from the next decision cycle. Positions already open keep the stops set at entry.

### 6.2 Example rules

The numbers below are illustrative starting values for the user to set, not recommendations.

| Rule | Starting value | Hard cap (set in code) | Chat can change it |
| --- | --- | --- | --- |
| Max risk per trade | 1% of capital | 2% | Yes, with confirmation |
| Max open positions | 3 | 5 | Yes, with confirmation |
| Daily loss limit | 2% of capital | 3% | Lower freely; raise only up to the cap |
| Stop-loss method | ATR-based | Cannot be removed | Tighten only |
| Trading mode | Paper | None | Back to paper: yes. To live: website button only |
| Watchlist | User's stocks | None | Yes |

### 6.3 Governance principles

- **Asymmetry.** Changes that reduce risk apply at once. Changes that increase risk need explicit confirmation and stay under the hard caps.
- **Caps live outside the database.** The hard caps are in code or a read-only config that neither chat nor any agent can write.
- **Live mode is a website-only action.** A chat message, however worded, cannot enable real-money trading.
- **Authenticated source.** Only the signed-in user's own messages can change rules. Text arriving through news or any tool result is never treated as an instruction.
- **Full audit trail.** Every change is visible on the audit page and can be reverted.

## 7. Autonomous research pipeline

The agents research on their own in five parallel streams and write the results to shared memory, where the Analyst merges them with the user's watchlist. Code does the fetching, deduplication and first-pass ranking, so the language model reads only short clustered summaries.

### 7.1 Research streams

| Stream | Agent | Example inputs | Written to memory |
| --- | --- | --- | --- |
| User watchlist | Scout | Quotes, candles and technical tags for the user's stocks | signals (source "user") |
| Market scan | Scout | Top gainers and losers, volume spikes, 20-day breakouts, option-chain open-interest changes | signals (source "agent") |
| Company news and earnings | News and Sentiment | Exchange filings, results calendar, headlines on listed companies | research\_notes, signals |
| Sentiment | News and Sentiment | Headline tone per stock and sector, clustered and scored | Sentiment score on each note |
| Global and macro | Global Macro | Overnight US markets, rate expectations, crude oil, dollar index, USD/INR, Asian indices, GIFT Nifty, FII and DII flows, geopolitical events | A market-regime note and sector tilts |

### 7.2 From international news to Indian stocks

The Global Macro agent turns overseas developments into a pre-market note on likely direction and affected sectors. The links below are starting hypotheses that the agent tests against live data, not fixed rules.

- **Crude oil:** oil marketing companies, aviation and paints on one side, upstream producers on the other.
- **US demand and USD/INR:** IT services exporters.
- **US rates and the dollar:** foreign institutional flows, banks and financials.
- **Asian and commodity markets:** metals and export-linked sectors.
- **GIFT Nifty and overnight Wall Street:** the opening bias for index trades.

Each note records which headlines or data points support it, and the Analyst may use it only as context, never as a standalone trade trigger.

### 7.3 Discipline in the pipeline

- **Facts and inference are kept apart.** A note states what was reported, then separately what the model infers, with source links for the first.
- **Primary sources first.** Exchange filings and company statements outrank aggregators and social posts, and low-quality sources are skipped.
- **One ranking for both origins.** Watchlist and discovered stocks enter the same ranking with a source tag, so the user can later compare hit rates by origin.
- **Time-stamped inputs.** Each item stores when it was fetched, and items older than a set number of hours are dropped for intraday decisions. This also prevents look-ahead in paper evaluation.
- **Data feeds are the user's choice.** Quotes and option chains come from the broker APIs. The news and global-data sources are still to be selected and should be checked for licence terms and latency.

## 8. Trade decision and execution

The Analyst proposes and code decides: no trade happens unless the Risk Manager passes it, and paper and live modes share one pipeline that differs only in its last step.

### 8.1 Decision flow

1. The Analyst reads the day's signals and research notes in one batched call and ranks the candidates.
2. For each selected candidate it returns a structured proposal: symbol, direction, instrument, entry, target, rationale, confidence and source tag ("user" or "agent").
3. Code computes the stop (from volatility, for example ATR) and the position size (from the risk-per-trade rule). The model may suggest a tighter stop but never a looser one.
4. The Risk Manager checks open positions, risk per trade, the daily loss limit, order rate, market hours and allowed instruments. Any veto is logged with its reason.
5. A passed proposal goes to the paper engine by default, or to the Executor in a live mode.
6. The Monitor watches live prices and exits at the stop or target in code, with no model call.

### 8.2 Paper trading that resembles live trading

Paper results are useful only if they carry real frictions. The paper engine therefore fills at the next available price after the proposal time plus an assumed slippage, charges brokerage, exchange fees and the current STT rates (Section 2.2), obeys the same order-rate limit, marks positions to market, and squares off intraday positions at the close. When a trade ends, the dashboard shows its net profit or loss after costs.

### 8.3 Autonomy levels

| Mode | Who approves each trade | Orders sent to the broker |
| --- | --- | --- |
| Paper (default) | Nobody | None; fills are simulated |
| Live, approve each trade | The user, on the dashboard | Yes, after approval |
| Live, autonomous | Nobody; the Risk Manager gates every order | Yes |

Both live modes are enabled only from the website button (Section 6.3). The recommended path is paper first, then live with approval at tiny size, and autonomous only if the criteria in Section 11 are met.

### 8.4 Order safety

Live orders go out through the broker's API or MCP from the whitelisted static IP. Each order carries a unique client reference to prevent duplicates and is previewed before sending. One community Groww MCP server shows a useful pattern: it defaults to dry run and requires a passing preview plus a single-use 60-second confirmation token for the exact order ([groww-mcp](https://glama.ai/mcp/servers/ritheshamin-oss/groww-mcp)). The Executor should adopt the same preview-then-confirm discipline.

## 9. Risk management and safety

Safety comes from deterministic code that sits between the model and the market, and from limits the model cannot edit. Industry guides to the SEBI framework also list a kill switch and order-level risk checks as expected parts of a compliant setup ([Antsheel](https://antsheel.com/blog/sebi-retail-algo-trading-rules-2026-india/)).

| Failure mode | Control |
| --- | --- |
| Model proposes an oversized or reckless trade | Size and stop are computed in code; caps on risk per trade and open positions |
| Model cites news that does not exist | Every note must carry source links; the user can inspect it; unsupported claims cannot trigger a trade |
| Malicious or misleading text in a headline or web page | Agents that read news have no order tools; news is stored as data and never obeyed as instructions |
| Stale quotes or broker API errors | Fail closed: no new entries, pending orders cancelled, user alerted |
| Runaway order loop | Rate limiter below the broker's 10 orders per second, unique order references, kill switch |
| Chat message tries to loosen limits | Hard caps in read-only config; live mode enabled only from the website |
| Expired login or changed IP | Agents stay idle until daily 2FA succeeds; alert on IP mismatch |
| Invalid or missing model output | No trade; the cycle is logged and retried at the next trigger |

### 9.1 Additional controls

- **Daily loss limit.** When reached, the system stops new entries for the day. The user chooses whether open positions are also squared off.
- **Kill switch.** One button on the website, and automatic triggers such as repeated order rejections, cancel open orders and halt all agents.
- **Stops can only tighten.** The model may move a stop closer to the price but never remove or widen it.
- **Instrument limits.** Naked option selling is disabled by default, because its losses are not capped. Early phases use defined-risk positions only.
- **Secure access.** The website can enable live mode, so it needs authentication and encrypted transport, and API keys must be stored encrypted on the NAS.
- **Compliance logging.** Every order is logged with its strategy ID, the inputs the agents saw and the model's output, so any trade can be explained afterwards.

## 10. Token and cost efficiency

The biggest saving is architectural: only four agents (News and Sentiment, Global Macro, Analyst and the main chat agent) call a language model, while scanning, risk, execution, monitoring and reporting are plain code. The techniques below cut model usage further.

| Technique | How it is applied |
| --- | --- |
| Event-driven calls | Call a model when a trigger fires (new catalyst, breakout, price alert, user message), not on a fixed timer |
| Two model tiers | A small, cheap model filters and summarises headlines; a stronger model ranks candidates and writes proposals |
| Prompt caching | Keep the system prompt, rules and agent instructions at the start of each prompt so repeated calls reuse them |
| Batching | Rank all candidates in one call instead of one call per stock |
| Compact inputs | Send a short summary per stock (trend, volume, catalyst, sentiment), never raw candles or full articles |
| Structured short outputs | Ask for brief JSON with fixed fields and a one-line rationale |
| Deduplicate and cache news | Cluster repeated stories, summarise each cluster once and reuse the summary until it expires |
| Rolling memory summaries | Compress old lessons into a short standing summary instead of replaying history |
| Market-hours scheduling | Run research bursts before the open and at set intervals, and switch agents off outside market hours |

To keep the saving real, the system should log tokens and cost per agent and per trade on the dashboard, so the user can see whether a stream earns its cost.

## 11. Evaluation methodology

The system is judged only on forward paper trading, net of costs, against simple benchmarks, with go-live thresholds fixed before the test starts.

### 11.1 Protocol

- **Forward only.** No performance claim rests on a backtest, because model memory can contaminate it (Section 3).
- **Thresholds first.** The rules, prompts and pass marks are written down before the test begins. Any later change to a prompt or rule is logged as a new version and restarts the count.
- **Long enough to matter.** The period should span trending and choppy sessions and at least one results season. A minimum such as three months is a sensible illustration, and the user should set the figure in advance.
- **Everything logged.** Inputs, model outputs, vetoes, fills and costs are stored for replay.

### 11.2 Metrics

| Metric | Why it matters |
| --- | --- |
| Net P&L after brokerage, STT and slippage | Gross profit can hide a loss after costs |
| Expectancy per trade | Average result of one trade, which decides whether the edge is real |
| Maximum drawdown | Whether the account would survive the worst stretch |
| Hit rate and payoff ratio | Explains where profit comes from |
| Risk-adjusted return (Sharpe-style) | Compares return with variability |
| Cost drag | Share of gross profit consumed by costs |
| Run-to-run variation | How often replaying identical inputs produces different proposals |

Expectancy per trade is:

```latex
E = p_w \cdot \bar{W} - (1 - p_w) \cdot \bar{L} - c
```

where p\_w is the win rate, W-bar the average win, L-bar the average loss, and c the average cost per trade.

### 11.3 Comparisons and attribution

- **Benchmarks.** Compare with Nifty buy-and-hold and with a rules-only baseline that ranks the same candidates without a language model. If the baseline does as well, the model is not earning its cost.
- **Origin.** Split results by source tag, user picks versus agent discoveries, and by research stream and sector.
- **Regime.** Report results on days the Global Macro note was bullish, bearish or neutral to see whether the macro layer adds anything.

### 11.4 Go-live gates

- [ ] Net expectancy is positive after costs over the pre-agreed period
- [ ] Maximum drawdown stayed within the user's limit
- [ ] Results beat both the benchmark and the rules-only baseline
- [ ] No unresolved control failure, such as a bypassed veto or a duplicate order
- [ ] The broker has confirmed static IP setup, strategy tagging and how prompt changes are treated
- [ ] Live trading starts at very small size with approve-each-trade enabled

## 12. Limitations and risks

The largest risk is statistical, not technical: the base rate for retail F&O is poor, and good architecture does not change it.

- **Poor base rates.** About 91% of individual F&O traders lost money in FY25 ([SEBI study summary](https://imrawal.com/Website/articles/sebi-fo-study-why-retail-traders-lose.html)), and higher STT since April 2026 raises the bar for short-term strategies.
- **Model behaviour.** LLM outputs vary between runs, and published evidence on live LLM trading is early and mixed (Section 3). A paper profit over a short period may be luck.
- **Data quality and latency.** Delayed or wrong news, quotes or macro data can produce confident but wrong proposals. Sentiment scores from a model are estimates, not measurements.
- **Overfitting by iteration.** Repeatedly adjusting prompts and rules after seeing results can fit the past. The version log and restart rule in Section 11.1 exist to limit this.
- **Regulatory ambiguity.** We found no SEBI text addressing LLM-driven strategies, and it is unclear whether prompt edits count as strategy changes. Rules and broker implementations also keep changing, so the broker's current policy governs.
- **Operational dependence.** The system relies on a stable static IP, the NAS staying online, and daily 2FA. A failure at the wrong moment can leave positions unmanaged unless broker-side stops are used.
- **Scope.** This paper is a design proposal. It reports no performance results and was not tested on live markets.

This paper is for information only and is not financial advice. Trading carries a real risk of losing money, and the user alone is responsible for decisions and for compliance with SEBI rules and the broker's terms.

## 13. Implementation roadmap

Build in four phases, moving to the next only when the gate between them is passed. The durations are the user's to set and are not fixed here.

&#91;embedded content: implementation roadmap · 4 phases, 3 gates\]

The system never skips a phase: it first proves that data and logins are reliable, then proves the strategy on paper with real costs, then risks a very small amount with the user approving each trade, and only then, if ever, runs autonomously with the same hard caps and kill switch.

**First tasks for phase 1**

- [ ] Confirm the NAS public IP is static and register it (plus a backup) with the broker
- [ ] Ask the broker how strategy tagging works and whether prompt edits count as a strategy change
- [ ] Create the database tables from Section 5 and the website pages that show them
- [ ] Add the rules form and the `update_rule` tool with hard caps stored outside the database
- [ ] Choose the news and global-data sources and check their terms and latency

## References

As of 18 October 2026. The Fyers notice and the Antsheel article were opened in full. The other entries were read from search excerpts and should be re-checked against the originals before anyone relies on them.

**Regulation and costs**

- [FYERS: New SEBI Framework for Retail Algo Trading from April 01, 2026](https://fyers.in/notice-board/new-sebi-framework-for-retail-algo-trading-from-april-01-2026)
- [Antsheel: SEBI retail algo trading rules in 2026](https://antsheel.com/blog/sebi-retail-algo-trading-rules-2026-india/)
- [Tradejini: What SEBI's new algo trading rules mean for you](https://www.tradejini.com/blogs/what-sebis-new-algo-trading-rules-mean-for-you)
- [Dozen Diamonds: Retail algo trading, SEBI's new rules explained](https://www.dozendiamonds.com/retail-algo-trading-sebi-new-rules/)
- [Outlook Money: STT hike from April 1, 2026](https://www.outlookmoney.com/invest/stt-hike-from-april-1-2026-budget-what-it-means-for-futures-and-options-traders)

**Retail trading outcomes**

- [Summary of SEBI F&O studies (FY22 to FY25)](https://imrawal.com/Website/articles/sebi-fo-study-why-retail-traders-lose.html)
- [Business Standard: 7 in 10 intraday traders in equity cash suffered losses in FY23](https://www.business-standard.com/amp/markets/news/7-in-10-intraday-traders-in-equity-cash-suffered-losses-in-fy23-sebi-study-124072400975_1.html)

**Broker MCP servers**

- [FYERS MCP](https://fyers.in/mcp)
- [Indian stock market MCP servers compared (DEV Community)](https://dev.to/govind_sisara/indian-stock-market-mcp-the-best-mcp-servers-for-nse-bse-data-2026-p28)
- [Zerodha: Connect your account to AI assistants with Kite MCP](https://zerodha.com/z-connect/featured/connect-your-zerodha-account-to-ai-assistants-with-kite-mcp)
- [groww-mcp, community server with dry-run safeguards](https://glama.ai/mcp/servers/ritheshamin-oss/groww-mcp)

**LLM trading agent research**

- [Reported alpha from LLM trading agents (arXiv 2605.16895)](https://arxiv.org/pdf/2605.16895)
- [AlphaForgeBench (arXiv 2602.18481)](https://arxiv.org/pdf/2602.18481)
- [AlphaCrafter (arXiv 2605.05580)](https://arxiv.org/pdf/2605.05580)
- [LiveTradeBench summary (alphaXiv)](https://www.alphaxiv.org/abs/2511.03628)
- [When Agents Trade: Agent Market Arena](https://www.researchgate.net/publication/396459334_When_Agents_Trade_Live_Multi-Market_Trading_Benchmark_for_LLM_Agents)
