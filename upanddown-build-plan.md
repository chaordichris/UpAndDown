# UpAndDown: Golf Trading System Build Plan

**Version:** 0.1 — Initial Architecture  
**Date:** 2026-04-15  
**Status:** Draft  

---

## 1. Executive Summary

UpAndDown is a systematic golf edge-discovery and strategy-validation framework built in Python. It ingests probabilistic forecasts from the DataGolf API, translates them into fair prices across multiple market types, compares those prices to live sportsbook lines, identifies daily edges, makes those edges easy to review in an operator UI, backtests the strategy, and tracks a bounded paper-bet sample to justify whether the strategy deserves real capital.

The system's philosophy is borrowed from Mark Spitznagel's approach to tail-risk investing: survival comes first, the default position is no action, and the portfolio is split between a core sleeve of small repeatable edges and a tightly capped convex sleeve for asymmetric long-odds opportunities.

In golf terms this means: matchups and 3-balls are the core edge engine because they are relative-value markets where DataGolf's player-level forecasts translate cleanly into fair prices and where the books' hold and pricing inefficiencies are most exploitable. Outrights are treated as a small convex sleeve — capped at a fixed percentage of capital — because they are high-variance, heavily juiced, and structurally hard to beat at scale even with good models.

The system starts with pre-tournament PGA Tour markets on regulated Indiana sportsbooks. It is designed to be modular so that additional tours, market types, books, and eventually live/in-play markets can be added without rewriting the core architecture.

Capital preservation is not a feature — it is the architecture. Every module that touches bet sizing, exposure, or execution must enforce hard limits that cannot be overridden by the pricing engine or edge detector. The bankroll engine has veto power over every bet.

UpAndDown is not intended to become a full personal betting-history tracker. Dedicated bet-tracking applications can own long-term real betting records. This system should be excellent at three things: daily edge calculation, backtest visualization, and paper-trading proof. Real betting history can be imported later for analysis and visualization.

---

## 2. Guiding Principles

**2.1 Survival first.** No single tournament, week, or losing streak should threaten the bankroll. The system must enforce hard drawdown brakes and reserve capital that is never deployed. If the system is unsure whether to bet, the correct answer is no bet.

**2.2 No-bet is the default.** You need a reason TO bet — a quantified edge above a minimum threshold — not a reason NOT to bet. The system should produce more "no action" outputs than bet tickets. A week with zero bets is a successful week if no genuine edge existed.

**2.3 Core vs. convex.** Approximately 85-90% of capital at risk should be in the core sleeve (matchups, make-cut, top-N) where edges are small, repeatable, and measurable. The remaining 10-15% is the convex sleeve (outrights) where individual bets are sized small and the payoff structure is asymmetric. These two sleeves have separate budgets, separate sizing rules, and separate performance tracking.

**2.4 Correlation is the hidden killer.** Golf creates correlated exposure by default: every golfer in the same tournament shares weather, course conditions, and field strength. If you bet Golfer A in a matchup, Golfer A to make the cut, and Golfer A in an outright, you are three times long Golfer A. The risk engine must aggregate exposure by golfer, by tournament, and by correlated cluster (e.g., all bets that benefit from a specific weather outcome).

**2.5 Robustness over overfitting.** DataGolf's model is the baseline truth. The system should translate DataGolf's forecasts into fair prices — not try to build a better golf model from scratch. Overlays should be systematic, justified, and small. If an overlay doesn't improve out-of-sample CLV over 30+ tournaments, remove it.

**2.6 CLV is the primary diagnostic.** Closing Line Value — whether you consistently beat the line that the market settles on — is the most reliable signal of edge in sports betting. ROI is noisy over golf sample sizes. CLV tells you if your process is good even when results are bad. The system must track CLV on every bet.

**2.7 Calibration over accuracy.** A well-calibrated model that says "this golfer has a 60% chance of winning this matchup" and is right 60% of the time is more valuable than an overconfident model that says 75% and is right 65% of the time. The pricing engine should be tested on calibration, not just accuracy.

**2.8 Auditability.** Every bet decision must be traceable from raw data through fair price, edge calculation, sizing decision, and execution. The system is its own audit trail. No magic numbers, no manual overrides without logging, no "I just felt good about this one."

---

## 3. Scope Definition

### 3.1 MVP In-Scope

**Tours:** PGA Tour only.

**Markets:**
- Tournament matchups (2-ball head-to-head)
- Tournament 3-balls
- Make/miss cut
- Top-10 finish
- Top-20 finish
- Outrights (convex sleeve only, small fixed units)

**Books:** DraftKings, FanDuel (both available in Indiana, both have golf markets, both have accessible odds).

**Data sources:** DataGolf API (pre-tournament forecasts, player skill ratings, historical results, field data).

**Execution:** Manual. The system generates bet tickets with sizing. The human places bets through book apps/websites.

**Operator UI:** A simple local UI for daily candidate review, backtest review, and paper-validation workflows.

**Validation:** Bounded paper-bet tracking for proof of strategy quality, including settlement, CLV, attribution, and phase-gate evidence.

### 3.2 MVP Out-of-Scope

- Live/in-play markets
- Round-level matchups and props
- Player performance props (birdies, eagles, hole-in-one)
- Same-game parlays and exotic bets
- European Tour, DP World Tour, LIV Golf, Korn Ferry Tour, LPGA
- BetMGM, Caesars, bet365, Fanatics, Hard Rock (added in Phase 6)
- Kalshi or any prediction/event market venue
- Automated execution (API-based bet placement)
- Machine learning models beyond DataGolf as baseline
- Full personal bet-history tracking product
- Mobile app

### 3.3 Later Phases

**Phase 2-3:** Add BetMGM, Caesars. Add round-level matchups. Add first-round leader.

**Phase 4-5:** Add live/in-play markets. Add automated or semi-automated execution. Add Kalshi if legally available. Add DP World Tour.

**Phase 6+:** Add LIV if DataGolf covers it. Add player props. Add SGP decomposition if edge exists. Explore ML overlays on top of DataGolf baseline.

---

## 4. End-to-End Architecture

### 4.1 Data Ingestion

Two primary data sources feed into the system:

**DataGolf API:** Pre-tournament skill ratings, win probabilities, make-cut probabilities, top-N probabilities, and historical results for every player in the field. Polled at configurable intervals (daily during tournament weeks, less frequently otherwise). The API returns JSON. Each response is stored as-is in a raw data store before any transformation.

**Sportsbook odds:** Pre-tournament lines for matchups, 3-balls, make-cut, top-N, and outrights from DraftKings and FanDuel. Ingested via web scraping, API (if available), or odds aggregation services. Each snapshot is timestamped and stored raw. Multiple snapshots per day capture line movement.

Each data source has its own ingestion module that implements a common interface: `fetch()`, `validate()`, `store_raw()`. New sources are added by implementing this interface.

### 4.2 Normalization

Raw data arrives in source-specific formats. The normalization layer converts everything to a common internal representation:

- American odds → implied probability → decimal odds
- Player names → canonical player IDs (DataGolf's player IDs are the primary key)
- Tournament names → canonical tournament IDs
- Market types → canonical market type enum
- Timestamps → UTC

The normalization layer also handles vig removal: converting book odds into no-vig implied probabilities using standard methods (multiplicative, power, Shin, additive). The choice of vig removal method is configurable and logged.

### 4.3 Storage

SQLite for MVP. The schema is designed to be portable to PostgreSQL without structural changes. Storage is organized into:

- **Raw tables:** Immutable, append-only records of exactly what each API returned and when.
- **Normalized tables:** Transformed, deduplicated data in the common schema. Still immutable — new snapshots create new rows, they don't update old ones.
- **Derived tables:** Model outputs, bet tickets, outcomes, CLV calculations. These reference the normalized tables by ID.

All tables carry `created_at` timestamps and source identifiers. Nothing is ever deleted.

### 4.4 Feature Generation

Features are derived from normalized data and DataGolf forecasts. For MVP, features are thin — the primary "model" is just DataGolf's own probabilistic forecasts. The feature layer exists as a structural hook for later overlays. Initial features:

- DataGolf win probability per player per tournament
- DataGolf make-cut probability
- DataGolf top-N probabilities
- Derived matchup fair odds (from individual probabilities)
- Derived 3-ball fair odds
- Historical CLV capture rate per market type
- Book-specific hold/vig by market type

### 4.5 Fair Odds and Pricing

The pricing engine translates DataGolf's individual player probabilities into fair prices for each market type:

- **Matchups:** P(A wins matchup vs B) derived from DataGolf's individual finish distributions. This requires either DataGolf's head-to-head probabilities directly (if available via API) or a simulation/copula approach using individual forecast distributions.
- **3-balls:** P(A wins 3-ball vs B and C), same approach extended to three players.
- **Make-cut / top-N:** Directly from DataGolf's probabilities.
- **Outrights:** Directly from DataGolf's win probabilities.

The output is a fair price for every market that has a corresponding book line. Fair prices include no vig.

### 4.6 Edge Detection

Edge = (fair probability − implied book probability). The edge detector compares the pricing engine's fair odds against the normalized, vig-removed book odds. A bet is a candidate if:

1. The edge exceeds a configurable minimum threshold (e.g., 3% for core, 8% for convex).
2. The fair price and book price are both from recent data (staleness check).
3. The market settles cleanly (no ambiguous settlement rules for this market/book combination).

The edge detector outputs a ranked list of bet candidates with: market, player(s), fair price, book price, edge size, book, and timestamp.

### 4.7 Bankroll and Exposure Engine

The bankroll engine is the final gatekeeper. It takes the ranked bet candidates and applies:

1. **Sizing:** Fractional Kelly (configurable, default 0.25 Kelly) for core bets. Fixed small units for convex bets.
2. **Exposure limits:** Per-golfer cap, per-tournament cap, per-book cap, per-sleeve cap.
3. **Correlation check:** If adding this bet would create excessive correlated exposure (multiple bets on the same golfer or same outcome cluster), reduce or reject.
4. **Drawdown check:** If the bankroll is in a drawdown state, apply the relevant brake (reduced sizing or paper-trade-only).
5. **Reserve check:** Ensure the reserve capital is never touched.

The output is a set of approved bet tickets with exact stake amounts, or a "no bet" decision with a logged reason.

### 4.8 Execution and Paper-Validation Layer

For MVP, execution is manual and bounded to validation. The system outputs bet tickets as a structured report or operator UI view:

```
Tournament: The Players Championship
Market: Matchup — Scottie Scheffler vs. Rory McIlroy
Book: DraftKings
Side: Scheffler -120
Fair price: -138
Edge: 4.2%
Stake: $45 (0.9% of active bankroll)
Sleeve: Core
```

During the paper-validation period, the human records the actual line that would have been obtained and the paper stake. The execution module records enough to support CLV, attribution, settlement, and auditability: ticket ID, timestamp, actual odds, stake, result, and any notes (line moved, bet rejected, etc.).

Long-term real betting history is not a core product surface. If needed later, it should be imported from dedicated tracking apps and analyzed alongside UpAndDown backtest and paper-proof artifacts.

### 4.9 Backtesting

The backtesting module replays historical tournaments through the full pipeline using only data that would have been available at the time. It is structurally identical to the live pipeline — same pricing engine, same edge thresholds, same sizing rules — but reads from historical data instead of live feeds.

Key requirement: walk-forward only. The backtester must never use closing lines to make opening-line decisions, and must never use future tournament data to inform current-tournament features.

### 4.10 Monitoring, Reporting, and Visualization

Weekly and per-tournament reporting:

- Bet log: every bet placed with edge, size, result, P&L
- CLV report: opening edge vs closing edge for every bet
- ROI by market type, by book, by edge bucket
- Calibration chart: predicted probability vs observed frequency
- Drawdown chart: bankroll over time with drawdown annotations
- Exposure report: aggregate exposure by golfer, by tournament, by sleeve
- Alerts: bets with negative CLV (line moved against us), rejected bets, staleness warnings

Daily and backtest UI requirements:

- Candidate board: current tournament, market, book, side, fair price, book price, edge, staleness, threshold/FDR status, and recommended action.
- Backtest dashboard: cumulative P&L, drawdown, CLV, ROI by market type, edge buckets, bet count, sample-size warnings, and tournament coverage.
- Paper-proof dashboard: bounded paper sample, CLV, attribution, unresolved actions, and phase-gate readiness.
- Bet-history import view, if added later, must consume external tracker exports rather than replacing those trackers.

---

## 5. Repository and Project Structure

```
golf-trading/
│
├── README.md                          # Project overview, setup, quickstart
├── agent.md                           # Project charter for agentic development
├── pyproject.toml                     # Python project config, dependencies
├── Makefile                           # Common commands: test, lint, run, backtest
│
├── config/
│   ├── settings.yaml                  # All configurable parameters
│   ├── books.yaml                     # Book-specific config (markets, rules, limits)
│   ├── .env.example                   # Required env vars template
│   └── logging.yaml                   # Logging configuration
│
├── docs/
│   ├── architecture.md                # This document (or a distilled version)
│   ├── data-dictionary.md             # Every table, field, enum defined
│   ├── adr/                           # Architecture Decision Records
│   │   ├── 001-why-python.md
│   │   ├── 002-datagolf-as-anchor.md
│   │   ├── 003-matchups-before-outrights.md
│   │   └── ...
│   └── skills/                        # Skill specs for agentic work
│       ├── datagolf-ingestion.md
│       ├── odds-normalization.md
│       └── ...
│
├── src/
│   ├── __init__.py
│   │
│   ├── ingestion/                     # Data fetching from external sources
│   │   ├── __init__.py
│   │   ├── base.py                    # Abstract ingestion interface
│   │   ├── datagolf.py                # DataGolf API client
│   │   └── sportsbooks.py            # Book odds fetching (DK, FD, etc.)
│   │
│   ├── normalization/                 # Raw → common format transformations
│   │   ├── __init__.py
│   │   ├── odds.py                    # Odds format conversions
│   │   ├── vig.py                     # Vig removal methods
│   │   ├── players.py                 # Player name/ID resolution
│   │   └── dead_heat.py              # Dead-heat adjustment rules
│   │
│   ├── storage/                       # Database models and access
│   │   ├── __init__.py
│   │   ├── models.py                  # SQLAlchemy/dataclass table definitions
│   │   ├── db.py                      # Connection, session, migration helpers
│   │   └── queries.py                 # Named query functions
│   │
│   ├── features/                      # Feature engineering
│   │   ├── __init__.py
│   │   ├── player.py                  # Player-level features
│   │   ├── tournament.py              # Tournament-level features
│   │   └── market.py                  # Market-level features (hold, CLV patterns)
│   │
│   ├── pricing/                       # Fair odds calculation
│   │   ├── __init__.py
│   │   ├── fair_odds.py               # DataGolf → fair price translation
│   │   ├── matchups.py                # Matchup/3-ball fair pricing
│   │   └── edge.py                    # Edge detection and ranking
│   │
│   ├── risk/                          # Bankroll, sizing, exposure
│   │   ├── __init__.py
│   │   ├── bankroll.py                # Bankroll state, reserves, sleeves
│   │   ├── sizing.py                  # Kelly and alternative sizing
│   │   ├── exposure.py                # Concentration and correlation limits
│   │   └── drawdown.py               # Drawdown brakes and stop conditions
│   │
│   ├── execution/                     # Tickets and bounded paper-validation records
│   │   ├── __init__.py
│   │   ├── tickets.py                 # Bet ticket generation and output
│   │   ├── logger.py                  # Bet placement logging
│   │   └── settlement.py             # Outcome recording and settlement
│   │
│   ├── backtest/                      # Historical replay
│   │   ├── __init__.py
│   │   ├── simulator.py               # Walk-forward replay engine
│   │   └── evaluator.py              # Metrics calculation
│   │
│   ├── monitoring/                    # CLV, reports, visualizations, alerts
│   │   ├── __init__.py
│   │   ├── clv.py                     # Closing line value tracking
│   │   ├── calibration.py            # Calibration analysis
│   │   └── reports.py                # Report generation
│   │
│   └── orchestration/                 # Scheduling and pipeline coordination
│       ├── __init__.py
│       └── pipeline.py               # End-to-end pipeline runner
│
├── tests/
│   ├── unit/                          # Isolated function tests
│   │   ├── test_odds.py
│   │   ├── test_vig.py
│   │   ├── test_sizing.py
│   │   └── ...
│   ├── integration/                   # Multi-module tests
│   │   ├── test_pipeline.py
│   │   └── test_backtest.py
│   └── fixtures/                      # Sample data for tests
│       ├── datagolf_response.json
│       ├── dk_odds_snapshot.json
│       └── ...
│
├── scripts/
│   ├── run_pipeline.py                # Daily pipeline entrypoint
│   ├── backtest.py                    # Backtest runner
│   ├── report.py                      # Generate reports on demand
│   └── seed_data.py                  # Load historical data
│
└── data/
    ├── raw/                           # Raw API responses (gitignored)
    ├── db/                            # SQLite database file (gitignored)
    └── reports/                       # Generated reports (gitignored)
```

**Key interfaces between components:**

| Producer | Consumer | Interface |
|----------|----------|-----------|
| `ingestion` | `storage` | `RawSnapshot` dataclass written to raw tables |
| `storage` | `normalization` | `queries.get_latest_raw()` returns raw records |
| `normalization` | `storage` | `NormalizedOdds` dataclass written to normalized tables |
| `features` + `pricing` | `edge` | `FairPrice` and `BookPrice` dataclasses compared |
| `edge` | `risk` | `BetCandidate` dataclass with edge, market, players |
| `risk` | `execution` | `BetTicket` dataclass with approved stake and limits |
| `execution` | `storage` | `PlacedBet` record written to bets table |
| `settlement` | `monitoring` | `BetOutcome` record triggers CLV and P&L calculation |

---

## 6. Skill Creation Plan

Each skill below is a self-contained capability module. Skills are defined by their interface (inputs/outputs) and can be built and tested independently.

### 6.1 DataGolf API Ingestion

**Objective:** Fetch pre-tournament forecasts, player ratings, field lists, and historical results from the DataGolf API and store them as raw, timestamped records.

**Inputs:** API key (from config), tournament schedule, list of endpoints to query.

**Outputs:** Raw JSON responses stored in `raw_datagolf_snapshots` table with tournament_id, endpoint, timestamp, and full response body.

**Dependencies:** Config/secrets module, storage module.

**Acceptance criteria:**
- Successfully authenticates and fetches data from all required DG endpoints.
- Handles rate limits gracefully (backoff and retry).
- Stores complete, unmodified API responses.
- Handles API errors (timeout, 4xx, 5xx) without crashing.
- Idempotent: re-running for the same tournament/timestamp doesn't create duplicates.

**Tests:**
- Unit: Mock API responses, verify parsing and storage.
- Integration: Fetch from live DG API sandbox (if available) or against recorded fixtures.
- Edge: Empty field, player withdrawn after field posted, API returns unexpected schema.

**Failure modes:** API schema changes silently (new fields or renamed fields). Mitigation: validate response against expected schema before storing. Rate limit exceeded during tournament week when polling frequently.

### 6.2 Sportsbook Odds Ingestion

**Objective:** Fetch pre-tournament odds for all in-scope market types from DraftKings and FanDuel. Store timestamped snapshots.

**Inputs:** Book configuration (which books, which market types), scraping/API config.

**Outputs:** Raw odds snapshots in `raw_book_snapshots` table with book_id, market_type, timestamp, full response.

**Dependencies:** Config module, storage module.

**Acceptance criteria:**
- Fetches odds for matchups, 3-balls, make-cut, top-10, top-20, outrights from DK and FD.
- Stores raw data before any transformation.
- Multiple snapshots per day to capture line movement.
- Handles market not yet posted, market removed, and market suspended states.

**Tests:**
- Unit: Parse fixture files mimicking each book's format.
- Integration: End-to-end fetch from live book (manual validation).
- Edge: Market exists on DK but not FD. Player name mismatch between books.

**Failure modes:** Books change HTML structure or API format without notice (the most common failure in sports betting systems). Mitigation: structural validation on every fetch; alert on parse failures. Books block scraping IPs. Mitigation: respect rate limits, use headless browser rotation if needed, monitor for blocks.

### 6.3 Odds Normalization

**Objective:** Convert raw odds from any source format to a common internal representation: implied probability (0-1), decimal odds, and American odds.

**Inputs:** Raw odds in American, decimal, or fractional format.

**Outputs:** `NormalizedOdds` dataclass with all three representations and a `source_vig` field.

**Dependencies:** None (pure math).

**Acceptance criteria:**
- Converts between American ↔ decimal ↔ implied probability losslessly (within floating-point precision).
- Handles edge cases: even odds (+100 / 2.00), heavy favorites (-10000), long shots (+50000).
- Round-trip: normalize → denormalize produces the original value.

**Tests:**
- Unit: Table-driven tests with 20+ known conversions covering the full range.
- Property: Round-trip fuzz testing.
- Edge: Zero odds, negative implied probability (invalid input), probabilities summing to > 2.0.

**Failure modes:** Floating-point precision issues at extreme odds (very heavy favorites or very long shots). Mitigation: use Decimal type for intermediate calculations if precision matters.

### 6.4 Vig Removal

**Objective:** Remove the book's built-in margin (vig/hold) from a set of odds to produce no-vig implied probabilities.

**Inputs:** A set of implied probabilities from a book that sum to > 1.0 (the overround).

**Outputs:** Adjusted implied probabilities that sum to 1.0, plus the calculated hold percentage.

**Dependencies:** Odds normalization.

**Acceptance criteria:**
- Implements at least two methods: multiplicative (proportional) and power method.
- Produces probabilities that sum to 1.0 (within tolerance).
- Correctly identifies the hold percentage.
- Configurable default method with ability to override per-market.

**Tests:**
- Unit: Known vig scenarios with hand-calculated expected outputs.
- Property: Output always sums to 1.0. Output probabilities are always between 0 and 1. Each output probability is less than or equal to the input.
- Edge: Two-way market vs. 150-way outright. Market with extreme vig (15%+). Market with near-zero vig.

**Failure modes:** Power method can behave oddly with very small fields or extreme vig. Mitigation: fall back to multiplicative when power method doesn't converge.

### 6.5 Dead-Heat and Settlement Rules

**Objective:** Correctly handle dead-heat reductions, withdrawal rules, and book-specific settlement variations for all in-scope markets.

**Inputs:** Market type, book, number of tied players, withdrawal timing.

**Outputs:** Adjusted payout multiplier, settlement status (win/loss/void/push/dead-heat-reduced).

**Dependencies:** Book configuration.

**Acceptance criteria:**
- Correctly applies dead-heat rules for top-N markets (e.g., 4 players tie for 10th in a top-10 market).
- Handles WD before round 1 (void), WD mid-tournament (book-specific: some books void, some settle as loss).
- Correctly handles matchup settlement when one player WDs (book-specific).
- Rules are configurable per book.

**Tests:**
- Unit: Every settlement scenario by book with expected output.
- Integration: Historical tournaments with known dead-heats, verify against actual book settlement.
- Edge: Three-way tie spanning the make-cut line. Player DQ vs WD.

**Failure modes:** Settlement rules change per book without notice. Mitigation: log every settlement decision with rule applied; flag any settlement that the system isn't confident about for manual review.

### 6.6 Player and Tournament Feature Engineering

**Objective:** Generate features that describe player form, course fit, tournament conditions, and field strength. For MVP, these are thin wrappers around DataGolf data; the structure exists for later enrichment.

**Inputs:** DataGolf forecasts, historical results, tournament metadata.

**Outputs:** Feature vectors per player per tournament, stored in the feature store.

**Dependencies:** DataGolf ingestion, storage.

**Acceptance criteria:**
- Produces a feature row for every player in every tournament field.
- For MVP: DataGolf skill rating, DataGolf win/top-N/make-cut probabilities, historical course results.
- Features are timestamped and versioned.
- No leakage: features for tournament T use only data available before T.

**Tests:**
- Unit: Feature calculation on fixture data.
- Leakage: Verify that features for tournament T never reference results from tournament T.
- Edge: Player's first appearance (no history). Tournament at a new course (no course history).

**Failure modes:** Data leakage is the most dangerous failure. It makes backtests look great and live performance collapse. Mitigation: strict temporal filtering in all feature queries; automated leakage detection tests.

### 6.7 Fair Odds Pricing

**Objective:** Translate DataGolf's player-level probabilities into fair prices for every in-scope market type.

**Inputs:** DataGolf forecasts for every player in the field.

**Outputs:** `FairPrice` for every market: matchup fair odds, 3-ball fair odds, make-cut fair odds, top-N fair odds, outright fair odds.

**Dependencies:** DataGolf ingestion, normalization.

**Acceptance criteria:**
- Matchup: P(A beats B) derived from DataGolf's individual probabilities. If DG provides head-to-head directly, use it. Otherwise, derive from finish distributions.
- 3-ball: P(A beats B and C).
- Tie handling: configurable (half-win, dead-heat reduction, or exclude ties).
- All fair prices are no-vig probabilities between 0 and 1.
- Fair prices for complementary sides of a market sum to 1.0 (matchup: P(A) + P(B) + P(tie) = 1).

**Tests:**
- Unit: Hand-calculated matchup and 3-ball prices from known DG probabilities.
- Calibration: Over a historical sample, do 60%-fair-price events happen ~60% of the time?
- Edge: Two players with identical DG ratings. Player with 0.1% win probability in a matchup vs. a heavy favorite.

**Failure modes:** The biggest risk is that DataGolf's individual probabilities don't compose correctly into matchup probabilities because of correlation (same course, same conditions). DataGolf may or may not account for this. Mitigation: track calibration by market type separately; if matchup calibration is poor, investigate whether a correlation adjustment is needed.

### 6.8 Edge Scoring

**Objective:** Compare fair prices against book prices and score each market by edge size, confidence, and actionability.

**Inputs:** `FairPrice` from pricing engine, `BookPrice` from normalized odds, configurable edge thresholds.

**Outputs:** Ranked list of `BetCandidate` records with: market, side, edge (%), fair price, book price, book, confidence score, staleness flag.

**Dependencies:** Fair odds pricing, odds normalization, vig removal.

**Acceptance criteria:**
- Edge = fair_probability − book_implied_probability (after vig removal).
- Candidates pass a minimum edge threshold (configurable, default 3% core / 8% convex).
- Staleness filter: fair price and book price must both be < N hours old.
- Confidence score incorporates: edge size, data freshness, historical CLV in this market type.

**Tests:**
- Unit: Known fair price + book price → expected edge calculation.
- Integration: Full pipeline from DG forecast + book odds → candidate list.
- Edge: Edge exists but line is stale. Edge exists but market is suspended. Edge is negative (book is sharper than our fair price).

**Failure modes:** Stale data producing phantom edges. Mitigation: strict freshness checks. Model is miscalibrated for a specific market type, generating systematic false edges. Mitigation: track CLV by market type; if CLV is negative for a market type over 20+ bets, flag for review.

### 6.9 Bankroll Sizing

**Objective:** Calculate the optimal stake for each bet candidate given the current bankroll state, the edge, and the risk constraints.

**Inputs:** `BetCandidate`, current bankroll state (active core, convex sleeve, reserve), sizing parameters (Kelly fraction, min/max stake).

**Outputs:** Stake amount in dollars, or rejection with reason.

**Dependencies:** Exposure control, drawdown module.

**Acceptance criteria:**
- Core bets: fractional Kelly (default 0.25x). Stake = kelly_fraction × edge / (odds − 1) × active_bankroll.
- Convex bets: fixed small unit (e.g., 0.5% of convex sleeve per bet).
- Hard floor: no bet below minimum book bet size.
- Hard ceiling: no single bet above 2% of total capital.
- Respects current sleeve budgets.

**Tests:**
- Unit: Known edge + bankroll → expected stake.
- Property: Stake is always ≥ 0 and ≤ hard ceiling. Stake never exceeds available sleeve budget.
- Edge: Edge is exactly at threshold. Bankroll is in drawdown (reduced sizing). Convex sleeve is fully deployed.

**Failure modes:** Kelly sizing is extremely sensitive to edge estimates. A small overestimate of edge produces a large overbet. Mitigation: fractional Kelly (0.25x) is the default, and it's deliberately conservative. The system should also cap Kelly-suggested stakes at the hard ceiling even if Kelly says to bet more.

### 6.10 Exposure and Concentration Control

**Objective:** Prevent dangerous concentration of risk by enforcing limits on exposure per golfer, per tournament, per book, and per correlated cluster.

**Inputs:** Proposed bet ticket, current portfolio of open bets, exposure configuration.

**Outputs:** Approval, reduction (with reduced stake), or rejection (with reason).

**Dependencies:** Bankroll sizing, storage (open bets query).

**Acceptance criteria:**
- Per-golfer limit: total exposure to any single golfer across all markets ≤ configurable cap (default 3% of active bankroll).
- Per-tournament limit: total exposure to any single tournament ≤ configurable cap (default 5% of total capital).
- Per-book limit: no more than a configurable percentage of capital at any single book.
- Correlation check: flag when multiple bets are effectively the same directional view (e.g., Golfer A matchup + Golfer A make-cut + Golfer A outright).

**Tests:**
- Unit: Portfolio with N open bets + proposed bet → expected approval/rejection.
- Integration: Simulate a full tournament week with many bet candidates; verify limits are never exceeded.
- Edge: Golfer appears in 5 different markets. Tournament with a very small field. All bets at one book.

**Failure modes:** Correlation detection is hard to get right. The simplest approach (aggregate by golfer name) catches the obvious cases but misses subtler correlations (e.g., "both golfers in this matchup benefit from calm weather, and I'm long both in separate matchups"). Mitigation: start simple (per-golfer aggregation) and add sophistication later.

### 6.11 Backtesting

**Objective:** Replay the full pipeline over historical tournaments to evaluate strategy performance with realistic constraints.

**Inputs:** Historical DataGolf data, historical book odds (if available), strategy configuration.

**Outputs:** Strategy replay results with P&L, CLV, calibration metrics, drawdown curve, and visualization-ready summaries.

**Dependencies:** All pricing, sizing, and risk modules; historical data store.

**Acceptance criteria:**
- Walk-forward: processes tournaments in chronological order using only past data.
- Uses the same code paths as the live pipeline (no separate "backtest mode" logic).
- Records every decision: bet placed, bet rejected (with reason), no edge found.
- Computes: total ROI, ROI by market type, CLV (if closing line data available), max drawdown, Sharpe-like ratio, calibration.

**Tests:**
- Unit: Simulate 3 tournaments with fixture data, verify metrics match hand calculations.
- Leakage detection: Run with intentionally leaked future data, verify it changes results (confirms the test would catch leakage).
- Edge: Tournament with no edges found (zero bets week). Tournament with all bets losing.

**Failure modes:** The biggest failure is data leakage producing unrealistically good results. The second biggest is survivorship bias — only backtesting on tournaments where you had data, missing the ones where data gaps would have caused problems. Mitigation: log every data gap and missing market; report the percentage of tournaments with complete data.

### 6.12 CLV Tracking

**Objective:** Record the closing line for every bet placed and compare it against the opening/placement line to calculate Closing Line Value.

**Inputs:** Placed bet records, closing line snapshots (final odds before tournament starts).

**Outputs:** CLV per bet, aggregate CLV by market type, by book, and over time.

**Dependencies:** Sportsbook ingestion (for closing lines), execution logger.

**Acceptance criteria:**
- Captures closing line for every market where a bet was placed.
- CLV = (fair_probability_at_close − implied_probability_at_placement). Positive CLV means you beat the close.
- Also computes: naive CLV (close vs. placement), and model CLV (your fair price vs. close).
- Aggregate statistics with confidence intervals.

**Tests:**
- Unit: Known placement odds + closing odds → expected CLV.
- Integration: Full pipeline with historical data, verify CLV calculation end-to-end.
- Edge: Market removed before close (no closing line available). Line doesn't move at all.

**Failure modes:** Missing closing line data for some bets (market taken down, or data collection gap). Mitigation: flag bets with missing CLV data; report CLV statistics both with and without these bets.

### 6.13 Reporting, Daily Edge UI, and Backtest Visualization

**Objective:** Generate periodic and on-demand reports summarizing system performance, daily edge candidates, backtest results, paper-validation evidence, and risk state.

**Inputs:** Bet candidates, paper-validation records, outcomes, CLV data, bankroll history, and backtest artifacts.

**Outputs:** Structured reports and UI views (CSV, HTML, terminal, or local web/static UI) covering: daily edge board, P&L summary, CLV analysis, calibration, drawdown, exposure, backtest results, and paper-proof readiness.

**Dependencies:** All monitoring modules, storage.

**Acceptance criteria:**
- Current tournament candidate board is easy to review without raw SQL or raw CLI output.
- Backtest results include visualization-ready cumulative P&L, drawdown, CLV, ROI by market, and edge-bucket summaries.
- Weekly report generated on demand.
- Per-tournament summary.
- Paper-proof dashboard for the bounded validation sample.
- All reports are reproducible (same inputs produce same output).

**Tests:**
- Unit: Generate report from fixture data, verify contents.
- Snapshot: Compare generated report against a known-good snapshot.

**Failure modes:** Reports that look great because of one big win masking poor process. Mitigation: always show CLV alongside ROI. Always show sample size alongside hit rates.

### 6.14 Config and Secrets Management

**Objective:** Centralize all configurable parameters and sensitive credentials in a structured, validated configuration system.

**Inputs:** `settings.yaml`, `books.yaml`, `.env` file.

**Outputs:** Typed configuration objects accessible throughout the system.

**Dependencies:** None (foundational).

**Acceptance criteria:**
- All magic numbers live in config, not in code.
- Secrets (API keys, credentials) are in `.env`, never in version control.
- Config is validated at startup: missing required values fail fast.
- Config changes don't require code changes.

**Tests:**
- Unit: Load valid config, verify all values parsed correctly. Load invalid config, verify clear error messages.
- Edge: Missing optional field (use default). Missing required field (fail with message). Invalid type (string where int expected).

**Failure modes:** Config drift: the config file says one thing but the code ignores it and uses a hardcoded value. Mitigation: no hardcoded values anywhere; all configurable parameters are read from the config object.

### 6.15 Orchestration and Scheduling

**Objective:** Coordinate the end-to-end pipeline: when to fetch data, when to run pricing, when to generate tickets, when to collect results.

**Inputs:** Schedule configuration, tournament calendar.

**Outputs:** Pipeline execution logs, triggered module runs.

**Dependencies:** All other modules.

**Acceptance criteria:**
- Daily pipeline: fetch DG data → fetch book odds → normalize → price → detect edges → size → output tickets.
- Tournament-week pipeline: higher polling frequency, multiple runs per day.
- Off-week pipeline: minimal (just update historical data, generate reports).
- Handles partial failures gracefully (if book odds fetch fails, still run with DG data and flag missing markets).

**Tests:**
- Unit: Mock all modules, verify orchestration calls them in the correct order.
- Integration: Run the full pipeline on fixture data.
- Edge: One module fails mid-pipeline. Two modules compete for the same database lock.

**Failure modes:** Silent failures where a module returns empty data and downstream modules proceed as if everything is fine. Mitigation: every module validates its inputs and outputs; empty results are explicitly handled (logged, flagged, or raised).

### 6.16 Data Quality Validation

**Objective:** Catch bad, stale, or anomalous data before it reaches the pricing engine.

**Inputs:** Raw and normalized data from any source.

**Outputs:** Validation pass/fail with specific error messages. Quarantined bad records.

**Dependencies:** Storage module.

**Acceptance criteria:**
- Odds validation: probabilities between 0 and 1, overround within expected range (100-130% for matchups, 100-200% for outrights).
- Field validation: tournament field size within expected range (70-160 players). Player IDs resolve to known players.
- Freshness: data timestamps are within expected recency window.
- Anomaly detection: flag odds that move more than a configurable threshold since last snapshot (possible bad data vs. real movement).

**Tests:**
- Unit: Feed known-good and known-bad data through validation.
- Edge: Odds of exactly 1.0 (even money). Player with no DataGolf record. Tournament with 30 players (small field).

**Failure modes:** Validation too strict (rejects good data during unusual but legitimate conditions like a WD-reduced field) or too loose (lets through bad data). Mitigation: validation rules are configurable; anomaly flags are warnings, not hard blocks, unless they fail basic sanity checks.

---

## 7. Agentic Work Decomposition

### WS-1: Foundation

**Purpose:** Establish the repo, config system, storage layer, and core data models.

**Prerequisites:** None.

**Deliverables:** Initialized repo with pyproject.toml, Makefile, config loading, database schema, models, connection management, and base test infrastructure.

**Handoff artifacts:** Working `make test` command, empty database that migrates cleanly, config loading from settings.yaml and .env.

**Parallelizable:** Config and storage can be built in parallel by two agents.

**Sequential:** Storage schema must be finalized before ingestion begins.

### WS-2: Data Ingestion

**Purpose:** Fetch data from DataGolf and sportsbooks and store raw snapshots.

**Prerequisites:** WS-1 (storage, config).

**Deliverables:** DataGolf client, sportsbook client(s), raw data tables populated, validation checks.

**Handoff artifacts:** Raw data in the database for at least 2 tournaments (can use historical data seeded from files if API access is limited).

**Parallelizable:** DataGolf ingestion and sportsbook ingestion can be built in parallel since they share only the storage interface.

**Sequential:** Must complete after WS-1.

### WS-3: Normalization and Data Quality

**Purpose:** Transform raw data into the common internal format. Validate data quality.

**Prerequisites:** WS-2 (raw data exists to normalize).

**Deliverables:** Odds normalization, vig removal, player ID resolution, dead-heat rules, data validation module.

**Handoff artifacts:** Normalized tables populated, validation report showing data quality for seeded data.

**Parallelizable:** Odds normalization, vig removal, and player resolution can be built in parallel. Dead-heat rules can be built in parallel.

**Sequential:** Must have raw data from WS-2 to normalize.

### WS-4: Pricing and Edge Detection

**Purpose:** Build the fair odds engine and edge detector.

**Prerequisites:** WS-3 (normalized data).

**Deliverables:** Fair odds pricing for all market types, edge scoring and ranking, bet candidate output.

**Handoff artifacts:** For a given tournament, a ranked list of bet candidates with edge sizes.

**Parallelizable:** Fair pricing and edge detection are tightly coupled; build sequentially within this workstream. But WS-4 can run in parallel with WS-5.

**Sequential:** Depends on WS-3.

### WS-5: Risk Engine

**Purpose:** Build bankroll management, sizing, exposure control, and drawdown brakes.

**Prerequisites:** WS-1 (config, storage). Can start in parallel with WS-2/WS-3/WS-4.

**Deliverables:** Bankroll state management, Kelly sizing, exposure limits, drawdown module.

**Handoff artifacts:** Risk engine that can accept a `BetCandidate` and return a `BetTicket` or rejection.

**Parallelizable:** Sizing and exposure control can be built in parallel. This entire workstream can be built in parallel with WS-2 through WS-4 since it doesn't depend on real data — it operates on the `BetCandidate` interface.

**Sequential:** Must be integrated with WS-4 output before paper trading begins.

### WS-6: Execution and Logging

**Purpose:** Build bet ticket output plus the minimal paper-validation records needed for settlement, CLV, attribution, and phase-gate evidence.

**Prerequisites:** WS-4 (bet candidates), WS-5 (approved tickets).

**Deliverables:** Ticket formatter, placement logger, settlement recorder.

**Handoff artifacts:** A complete paper-validation loop: candidates → sizing → tickets → (manual paper placement) → settlement.

**Parallelizable:** Ticket formatting and settlement recording can be built in parallel.

**Sequential:** Depends on WS-4 + WS-5 integration.

### WS-7: Backtesting

**Purpose:** Build the walk-forward backtesting engine, evaluation metrics, and visualization-ready summaries.

**Prerequisites:** WS-4 (pricing), WS-5 (risk), historical data.

**Deliverables:** Backtesting simulator, evaluator with all key metrics, leakage detection.

**Handoff artifacts:** Backtest report over at least 20 historical tournaments.

**Parallelizable:** Can be built in parallel with WS-6 since both depend on WS-4/WS-5 but not on each other.

**Sequential:** Must have historical data seeded (from WS-2 or fixture files).

### WS-8: Monitoring and Reporting

**Purpose:** Build CLV tracking, calibration analysis, daily edge UI/reporting, paper-proof reporting, and backtest visualization.

**Prerequisites:** WS-6 (bet outcomes exist), WS-7 (backtest results exist).

**Deliverables:** CLV module, calibration module, weekly report generator, drawdown charts.

**Handoff artifacts:** A complete report for at least one backtested season.

**Parallelizable:** CLV, calibration, and reporting modules can be built in parallel.

**Sequential:** Needs bet outcome data from WS-6 or WS-7.

---

## 8. MVP Definition

### What it includes

- DataGolf API integration for pre-tournament forecasts (PGA Tour).
- Odds from DraftKings and FanDuel for matchup markets.
- Vig removal and fair-odds pricing for matchups.
- Edge detection with a configurable minimum threshold.
- Fractional Kelly sizing (0.25x) with hard caps.
- Per-golfer and per-tournament exposure limits.
- Manual execution: system outputs bet tickets, human places bets.
- Bet logging: record what was placed, at what odds, for how much.
- Settlement recording: record outcomes.
- CLV tracking: compare placement odds to closing odds.
- Weekly report: bet log, P&L, CLV summary, drawdown.

### What it does not include

- Automated execution.
- More than 2 books.
- More than matchup markets (top-N and outrights are Phase 2).
- Any ML overlay on DataGolf.
- Live/in-play markets.
- Full bet-tracking dashboard.

### Minimum risk rules

- 50% of total capital in reserve (never deployed).
- 40% in active core sleeve.
- 10% in convex sleeve (not used in MVP — outrights are Phase 2).
- Max single bet: 2% of total capital.
- Max per tournament: 5% of total capital.
- Max per golfer: 3% of active bankroll.
- Drawdown brake: if active core is down 15% from peak, halve unit sizes.
- Stop condition: if active core is down 25% from peak, paper trade only until review.

### What success looks like

After 8-12 PGA Tour events (roughly 2-3 months):
- System has tracked 50+ bet candidates, placed 15-30 bets.
- CLV is measurable and the distribution is documented.
- If aggregate CLV is positive: the process is likely sound. Proceed to Phase 2.
- If aggregate CLV is approximately zero: the edge threshold may need tightening or the market is efficient. Investigate before increasing capital.
- If aggregate CLV is negative: the fair-pricing model is less accurate than the market. Stop live bets, diagnose, fix.
- ROI is tracked but NOT used as the primary success metric (too noisy over 30 bets).
- All bets are logged, all settlements are recorded, all reports are generating.
- No operational failures (data gaps, crashes, missed tournaments).

---

## 9. Risk and Bankroll Framework

### 9.1 Capital Structure

**Total capital (C):** The full amount allocated to this system.

**Reserve (50% of C):** Never deployed. This is the survival buffer. Its job is to ensure you can always restart after a worst-case drawdown. The reserve is not a "savings account to bet later" — it is permanent insurance.

**Active core sleeve (40% of C):** Deployed on core markets (matchups, make-cut, top-N). Sized via fractional Kelly. This is where repeatable edge lives.

**Convex sleeve (10% of C):** Deployed on outrights at fixed small units. This is the asymmetric payoff bucket. The expected return on this sleeve may be negative in most weeks; the goal is that rare wins more than compensate over a season.

### 9.2 Sizing Methodology

**Core sleeve — fractional Kelly:**

Kelly stake = (edge / (decimal_odds − 1)) × active_core_bankroll

The system uses a Kelly fraction (default 0.25) to account for edge estimation uncertainty. A 4% estimated edge on a -110 matchup at full Kelly would suggest ~4.2% of bankroll. At 0.25 Kelly, that's ~1.05% of active core.

The Kelly fraction is configurable but should rarely exceed 0.5. Higher fractions amplify both gains and drawdowns.

**Convex sleeve — fixed units:**

Each outright bet is a fixed fraction of the convex sleeve (default 0.5%). With a $1,000 convex sleeve, each outright bet is $5. The fixed-unit approach avoids Kelly's sensitivity to edge estimation on high-variance bets where the probability estimate has wide confidence intervals.

### 9.3 Hard Risk Caps

| Limit | Value | Scope |
|-------|-------|-------|
| Max single bet | 2% of total capital | Any bet |
| Max per tournament | 5% of total capital | Sum of all open bets for one event |
| Max per golfer | 3% of active core | Sum of all bets involving one golfer |
| Max per book | 60% of active capital | Not overweight on one book |
| Min edge (core) | 3% | Below this, no bet |
| Min edge (convex) | 8% | Below this, no outright bet |

### 9.4 Drawdown Brakes

| Active core drawdown from peak | Action |
|------|--------|
| −10% | Alert. Review all open positions and recent CLV. |
| −15% | Reduce all unit sizes by 50%. Continue betting at half size. |
| −20% | Reduce all unit sizes by 75%. Review edge model, CLV, and calibration. |
| −25% | Paper trade only. No real capital deployed until full review. |
| −35% | System halt. Complete model audit required before resuming. |

Drawdown is measured against the peak active-core bankroll, not the starting bankroll. This means early gains raise the drawdown trigger levels.

### 9.5 Stop Conditions and Review Triggers

- **Negative CLV over 20+ bets:** The model is worse than the market. Stop and diagnose.
- **CLV positive but ROI significantly negative over 50+ bets:** Possible sizing issue or bad luck variance. Review sizing parameters.
- **Three consecutive tournaments with zero edges found:** Possible data issue or market has adjusted. Investigate.
- **Any single bet exceeds hard caps:** Immediate system review — a bug exists in the risk engine.
- **Book account limited or restricted:** Adjust book allocation, possibly pause that book.

---

## 10. Modeling Roadmap

### Stage 1: DataGolf as Baseline (MVP)

Use DataGolf's pre-tournament forecasts as-is. The system's job is not to build a better golf model — it's to translate DataGolf's probabilities into fair prices and compare them against the books.

**Key tasks:** Build the fair-price translator for matchups, 3-balls, make-cut, top-N, and outrights. Validate calibration: do DataGolf's 60% probabilities actually hit 60% of the time?

**What you learn:** Whether the books are systematically mispricing relative to DataGolf's model, and in which markets.

**Expected timeline:** Phases 0-3 (first 4-8 weeks).

### Stage 2: Systematic Overlays

After 30+ tournaments of CLV data, look for patterns where DataGolf and the market systematically diverge:

- **Public bias:** Are popular/famous golfers overbet in matchups? (Likely yes — the matchup market is retail-heavy.)
- **Course fit:** Does DataGolf fully capture course-specific skill profiles, or can a course-history overlay improve predictions?
- **Field strength:** Does DataGolf properly adjust for weak fields (opposite-field events)?
- **Weather:** Do books adjust quickly enough when weather forecasts change?

Overlays should be small (1-3% adjustments to the base probability), justified by out-of-sample data, and validated via CLV tracking with and without the overlay.

**Expected timeline:** Phase 4-5 (months 3-6).

### Stage 3: Meta-Model for Confidence

Not all edges are equal. A 5% edge in a liquid matchup market with 10+ data points of CLV is more trustworthy than a 5% edge in a thin 3-ball market with 2 data points.

Build a meta-model that scores edge quality based on: historical CLV capture rate for this market type, data freshness, line movement (is the market moving toward or away from your position?), and market liquidity.

Use the confidence score to adjust sizing: higher confidence → bet closer to the Kelly fraction; lower confidence → bet less or skip.

**Expected timeline:** Phase 5-6 (months 6-12).

### Stage 4: Live and In-Play Extensions

Live markets are structurally different: faster data feeds, shorter decision windows, more volatile pricing. The architecture supports this (the pipeline is modular), but the pricing engine and execution layer need significant extensions.

Consider only after the pre-tournament system is profitable and well-understood.

**Expected timeline:** Phase 6+ (12+ months).

---

## 11. Backtesting and Evaluation Framework

### 11.1 Walk-Forward Validation

The backtester processes tournaments in strict chronological order. For each tournament:

1. Freeze the information state to what was available at the time (DG forecasts posted pre-tournament, book lines at time of publication).
2. Run the pricing engine, edge detector, and risk engine.
3. Record all bet decisions (placed, rejected, no edge).
4. Settle all bets using actual tournament results.
5. Update the bankroll state.
6. Advance to the next tournament.

No retraining, no parameter changes, no lookahead. The backtester must use the same code paths as the live pipeline.

### 11.2 Avoiding Leakage

**Sources of leakage to guard against:**

- Using closing lines to inform opening-line decisions.
- Using tournament results (even indirectly) in features for the same tournament.
- Using future DataGolf forecasts (their model updates over time).
- Selecting the Kelly fraction or edge threshold by optimizing on the full backtest period (this is overfitting).

**Mitigation:** Automated leakage tests that inject future data and verify it changes outcomes. Config parameters (Kelly fraction, edge threshold) should be set before the backtest runs, not tuned afterward.

### 11.3 Key Metrics

| Metric | What it measures | Target |
|--------|------------------|--------|
| CLV (aggregate) | Process quality: are you beating the closing line? | Positive |
| CLV (by market type) | Which markets have real edge? | Positive per market |
| ROI | Profit relative to total staked | Positive (but noisy) |
| Calibration | Do X% events happen X% of the time? | Brier score < baseline |
| Log loss | Probabilistic accuracy | Lower than book-implied |
| Max drawdown | Worst peak-to-trough in bankroll | < 25% of active core |
| Sharpe-like ratio | Risk-adjusted return (weekly P&L / weekly std) | > 0 |
| Hit rate (by market) | Win percentage per market type | Informational |
| Avg edge at placement | Mean edge size of bets taken | > min threshold |
| Avg CLV at close | Mean CLV of bets taken | Positive |
| Exposure concentration | Max % of bankroll in one golfer/tournament | < caps |
| Bet volume | Number of bets per tournament week | 5-15 (suspiciously high = model is too loose) |

### 11.4 Avoiding Self-Deception

Golf is a high-variance sport. A golfer with a 10% chance of winning a matchup can still win the matchup. Over 30 bets, you can be making correct +EV bets and still be down 15%.

**Rules for honest evaluation:**

- Never trust ROI over fewer than 100 bets. Use CLV instead.
- Always report confidence intervals alongside point estimates.
- Compare against a null model (random betting with the same sizing rules) to verify the strategy adds signal above noise.
- Run the backtest with at least 40 tournaments before drawing conclusions.
- If you tune a parameter and rerun the backtest, you've consumed the out-of-sample validity. Use a holdout set.

---

## 12. Data Model and Storage Recommendations

### 12.1 Storage Technology

**MVP: SQLite.** Simple, zero-config, single-file, works everywhere. All tables below work in SQLite.

**Phase 3+: PostgreSQL.** Migrate when concurrent access is needed (multiple pipeline processes) or when data volume exceeds ~1GB.

The schema uses standard SQL types and avoids SQLite-specific features. Migration should be a mechanical schema copy.

### 12.2 Core Tables

**tournaments**
```
tournament_id (PK), name, course, tour, start_date, end_date,
purse, field_size, datagolf_event_id, status, created_at
```

**players**
```
player_id (PK), datagolf_player_id, name_canonical, country,
created_at, updated_at
```

**player_aliases**
```
alias_id (PK), player_id (FK), alias_name, source (DK/FD/DG)
```

**raw_snapshots**
```
snapshot_id (PK), source (datagolf/dk/fd), endpoint, tournament_id,
fetched_at, response_body (JSON), status_code, is_valid
```

**normalized_odds**
```
odds_id (PK), snapshot_id (FK), tournament_id (FK), market_type,
player_id_1 (FK), player_id_2 (FK, nullable), player_id_3 (FK, nullable),
side, book, american_odds, decimal_odds, implied_prob, no_vig_prob,
hold_pct, captured_at
```

**forecasts**
```
forecast_id (PK), snapshot_id (FK), tournament_id (FK), player_id (FK),
forecast_type (win/top5/top10/top20/mc), probability, datagolf_skill_rating,
captured_at
```

**fair_prices**
```
fair_price_id (PK), tournament_id (FK), market_type,
player_id_1 (FK), player_id_2 (FK, nullable), player_id_3 (FK, nullable),
side, fair_prob, method, calculated_at
```

**bet_candidates**
```
candidate_id (PK), tournament_id (FK), market_type, side,
player_id_1, player_id_2, player_id_3, book, fair_prob, book_prob,
edge_pct, confidence_score, staleness_flag, created_at
```

**bet_tickets**
```
ticket_id (PK), candidate_id (FK), sleeve (core/convex),
proposed_stake, proposed_odds, kelly_fraction_used, sizing_method,
exposure_check_result, approved, rejection_reason, created_at
```

**placed_bets**
```
bet_id (PK), ticket_id (FK), book, actual_odds, actual_stake,
placed_at, notes, placement_method (manual/auto)
```

**bet_outcomes**
```
outcome_id (PK), bet_id (FK), result (win/loss/push/void/dead_heat),
payout, profit_loss, settled_at, settlement_notes
```

**clv_snapshots**
```
clv_id (PK), bet_id (FK), closing_odds, closing_implied_prob,
placement_implied_prob, clv_raw, clv_model, captured_at
```

**bankroll_history**
```
entry_id (PK), date, total_capital, reserve, active_core, convex_sleeve,
drawdown_from_peak_pct, drawdown_state (normal/reduced/paper/halted),
notes
```

---

## 13. Operational Concerns

### 13.1 Line Staleness

Book odds change constantly. A line that was +150 two hours ago might be +130 now. The system must timestamp every odds snapshot and reject bet candidates where the book odds are older than a configurable threshold (default: 2 hours for pre-tournament, 5 minutes for live).

Even with fresh data, the human must verify the line is still available before placing. The execution log should record the actual line obtained, not just the line the system recommended.

### 13.2 Rejected Bets

Books may reject bets (limit reached, odds changed, market closed). The system must log rejected bets alongside placed bets, including the reason if available. A high rejection rate at a specific book may indicate account limiting — track and alert.

### 13.3 Settlement Rule Differences

Each book has its own rules for edge cases. Key differences by book:

- **Withdrawals:** Some books void matchups if either player WDs before round 1. Others settle the remaining player as the winner. Others void only if the WD happens before tee time.
- **Dead heats:** Standard dead-heat rules apply for top-N markets, but the number of places and the specific method can vary.
- **Ties in matchups:** Some books push on ties, others have a draw option, others use a "including ties" or "excluding ties" market variant.

All settlement rules must be documented per book in `books.yaml` and used by the settlement module.

### 13.4 Legal and Jurisdiction

The system is designed for use in Indiana, where online sports betting is legal. Ensure compliance with Indiana gaming regulations. Do not place bets from states where online betting is not legal. Do not use VPNs to circumvent geolocation.

Kalshi is a CFTC-regulated exchange with its own legal requirements. Validate availability in Indiana before integrating.

### 13.5 API Rate Limits

DataGolf has rate limits (documented in their API docs). Respect them. Use caching and polling intervals to stay well below limits.

Sportsbook scraping may have implicit rate limits. Aggressive polling can trigger blocks. Use respectful intervals and monitor for soft blocks.

### 13.6 Logging and Auditability

Every system decision is logged with:
- What data was used (snapshot IDs).
- What the fair price was.
- What the book price was.
- What the edge was.
- Whether the bet was approved or rejected (with reason).
- What the actual execution was.
- What the outcome was.

Logs are retained indefinitely. They are the system's self-audit mechanism.

---

## 14. Build Order

### Phase 0: Foundation (Week 1-2)

Initialize repo. Set up project structure, pyproject.toml, Makefile, CI (lint + test). Implement config loading and validation. Design and implement database schema. Write ADRs 001-005. Seed the database with fixture data for 2-3 historical tournaments (hand-curated or from DataGolf historical exports).

**Exit criterion:** `make test` runs and passes. Config loads. DB migrates. Fixture data is queryable.

### Phase 1: Ingestion and Normalization (Week 2-4)

Build DataGolf API client. Build DraftKings and FanDuel odds ingestion. Build odds normalization and vig removal. Build player name/ID resolution. Build data quality validation. Fetch and store real data for an upcoming tournament.

**Exit criterion:** Raw and normalized data exists in the DB for at least 2 tournaments. Validation reports show data quality metrics.

### Phase 2: Pricing and Risk (Week 4-6)

Build fair-odds pricing engine for matchups (top priority), then make-cut, top-N, outrights. Build edge detector. Build bankroll sizing (Kelly). Build exposure control. Build drawdown module. Integrate pricing → edge → risk pipeline.

**Exit criterion:** Given a tournament's data, the system produces a ranked list of bet candidates with approved stake sizes.

### Phase 3: Paper Trading (Week 6-10)

Build the daily edge review UI, execution/ticket module, settlement recorder, CLV tracker, backtest review output, and paper-proof report. Run the full pipeline on 4-6 live tournaments without placing real bets. Log only the paper-validation data needed to evaluate the strategy.

**Exit criterion:** Daily edge board is usable for tournament-week decisions. Backtest review artifacts are reproducible. Paper-validation sample covers 4+ tournaments with all proof metrics tracked. CLV distribution is documented. No system crashes or data gaps.

### Phase 4: Shadow Live (Week 10-14)

Continue paper trading. Simultaneously start placing 5-10 real bets per tournament at minimum stakes (smallest possible bet sizes). Compare paper results to actual results. Validate execution (are you getting the lines the system recommends?).

**Exit criterion:** 20+ real bets placed. Actual execution matches paper trading closely (no systematic slippage).

### Phase 5: Small Capital Deployment (Week 14-20)

Deploy actual capital at the minimum risk configuration. Follow all drawdown rules. Monitor CLV weekly. Adjust nothing for at least 6 tournaments (resist the urge to tune).

**Exit criterion:** 50+ real bets. CLV data supports the decision to continue, reduce, or stop.

### Phase 6: Iteration and Expansion (Week 20+)

Add markets (top-N, outrights as convex). Add books (BetMGM, Caesars). Add tours (DP World). Build overlays only after holdout validation (Stage 2 modeling). Build confidence meta-model (Stage 3). Consider live markets (Stage 4). Add importers for external betting-history exports if real performance analysis needs them.

---

## 15. Deliverables Checklist

### Phase 0

- [ ] Initialized git repo with standard structure
- [ ] pyproject.toml with dependencies
- [ ] Makefile with `test`, `lint`, `run`, `backtest` targets
- [ ] settings.yaml, books.yaml, .env.example
- [ ] Database schema (all core tables)
- [ ] Config loading module with validation
- [ ] Storage module with connection management
- [ ] ADRs 001-005 written
- [ ] Fixture data for 2-3 historical tournaments
- [ ] CI pipeline (lint + test) passing
- [ ] agent.md project charter

### Phase 1

- [ ] DataGolf API client with all required endpoints
- [ ] DraftKings odds ingestion module
- [ ] FanDuel odds ingestion module
- [ ] Odds normalization (American ↔ decimal ↔ implied prob)
- [ ] Vig removal (multiplicative + power method)
- [ ] Player name/ID resolution module
- [ ] Data quality validation module
- [ ] Raw and normalized data for 2+ real tournaments
- [ ] Unit tests for all normalization functions (30+ test cases)
- [ ] Integration test: fetch → store → normalize → query

### Phase 2

- [ ] Fair-odds pricing: matchups
- [ ] Fair-odds pricing: 3-balls
- [ ] Fair-odds pricing: make-cut, top-10, top-20
- [ ] Fair-odds pricing: outrights
- [ ] Edge detection module
- [ ] Kelly sizing module
- [ ] Exposure control module
- [ ] Drawdown brake module
- [ ] Dead-heat and settlement rules module
- [ ] Integration test: full pipeline from data → bet tickets
- [ ] Backtest module (walk-forward simulator)
- [ ] Backtest report for 20+ historical tournaments

### Phase 3

- [ ] Bet ticket output (CSV + terminal)
- [ ] Bet placement logger
- [ ] Settlement recorder
- [ ] CLV tracker
- [ ] Weekly report generator
- [ ] Paper trading log for 4+ tournaments
- [ ] Calibration analysis for matchup pricing
- [ ] Documentation: operating procedures for paper trading week

### Phase 4

- [ ] Shadow-live execution log (real bets at minimum stakes)
- [ ] Execution quality analysis (paper vs. actual slippage)
- [ ] Updated calibration with live data
- [ ] CLV report with 20+ real bets

### Phase 5

- [ ] Full capital deployment at MVP risk config
- [ ] Weekly report cadence established
- [ ] 50+ bet CLV dataset
- [ ] Decision document: continue / adjust / stop

### Phase 6

- [ ] Top-N market integration
- [ ] Outright market integration (convex sleeve)
- [ ] Additional books (BetMGM, Caesars)
- [ ] Stage 2 overlays (at least one validated)
- [ ] Dashboard (HTML or notebook)

---

## 16. Recommended ADRs

Each ADR should be a short markdown file (1-2 pages) documenting: the decision, the context, the options considered, the rationale, and the consequences.

**ADR-001: Why Python.** Python is the default for data work, has mature libraries for statistics and data manipulation, is the most common language for sports betting tools, and is readable by agents and humans. Tradeoff: slower than Go or Rust for live-market latency, but pre-tournament markets don't need sub-second performance.

**ADR-002: DataGolf as anchor source.** DataGolf provides the best publicly available golf forecasting model. Building a competing model from scratch would take months and may not be better. The system translates DataGolf rather than competing with it. Tradeoff: single-source dependency. Mitigated by making the pricing interface abstract so alternative models can slot in.

**ADR-003: Supported books — DraftKings and FanDuel first.** Both are legal in Indiana, both have comprehensive golf markets, both have the largest liquidity. Additional books add marginal value in Phase 1 because the edge-finding matters more than line-shopping at this stage.

**ADR-004: Matchups before outrights.** Matchup markets are where DataGolf's model translates most cleanly into fair prices, where vig is lowest (relative to outrights), where sample sizes are largest, and where edges are most measurable via CLV. Outrights are high-vig, high-variance, and harder to evaluate. Core strategy should be matchups; outrights should be a controlled convex sleeve.

**ADR-005: Bankroll philosophy — Spitznagel-inspired.** Survival first, reserve capital always held back, strict drawdown brakes, two-sleeve structure (core + convex), fractional Kelly sizing. This is more conservative than most sports betting systems and deliberately so. The goal is long-term compounding, not maximizing short-term ROI.

**ADR-006: SQLite for MVP, PostgreSQL for scale.** SQLite is zero-config, file-based, and sufficient for a single-user system processing 2-3 tournaments per week. PostgreSQL adds when concurrency, scale, or JSON querying becomes a bottleneck. The schema is designed to be portable.

**ADR-007: Manual execution first.** Automated execution is risky (bugs place real bets), legally complex, and not necessary for pre-tournament markets where you have hours to act. Manual execution in Phase 1-4 de-risks the system and lets you validate the recommendation engine before adding automation.

**ADR-008: Testing philosophy.** Every module has unit tests. Integration tests cover the full pipeline. Property-based tests for math modules (normalization, sizing). Leakage detection tests for the backtester. Fixture data for reproducibility. Target: 80%+ test coverage on core modules (pricing, risk, normalization).

**ADR-009: No parlays or SGPs.** Parlays compound vig and compound estimation error. Same-game parlays are even worse because of hidden correlation that books exploit. The system avoids these entirely. If parlays are considered in the future, they require a dedicated correlation model and a separate ADR.

**ADR-010: Vig removal method selection.** Default to multiplicative (proportional) for two-way markets and power method for multi-way (outright) markets. The choice is configurable per market type. Shin method is available as an option but is more complex and harder to validate.

---

## 17. Output Format Requirements

This document is designed to be:

- **Specific:** Every module has a defined interface, acceptance criteria, and test list.
- **Implementation-oriented:** The repo structure, data model, and skill specs are directly buildable.
- **Modular:** Each skill is independently testable. Each workstream is independently deliverable.
- **Tool-agnostic:** Nothing here requires a specific IDE, agent, orchestration layer, or LLM.
- **Clear about assumptions:** DataGolf is the model (not a custom ML system). MVP is matchups only. Manual execution for Phases 0-4. Indiana jurisdiction.
- **Clear about MVP vs. future:** MVP is Sections 3.1 and 8. Everything else is explicitly labeled by phase.
- **Honest about failure modes:** Each skill lists where it's likely to break.

---

## Appendix A: Recommended First 30 Days

**Week 1:** Initialize repo, write ADRs 001-005, implement config and storage, design database schema, create fixture data. Write agent.md project charter. Goal: `make test` passes, DB migrates, config loads.

**Week 2:** Build DataGolf API client. Fetch real data for next upcoming PGA Tour event. Build odds normalization and vig removal. Write 30+ unit tests for math modules. Goal: real DataGolf data in the DB, normalized and queryable.

**Week 3:** Build DraftKings odds ingestion. Build player name resolution. Build fair-odds pricing for matchups. Build edge detector. Goal: given a tournament, produce a ranked list of matchup edges comparing DG fair price vs DK lines.

**Week 4:** Build bankroll sizing and exposure control. Build bet ticket output. Integrate full pipeline. Run the system for the first live tournament (paper only). Record everything. Goal: complete paper-trading run for one tournament with all metrics.

**Ongoing from Week 4:** Continue paper trading each tournament. Add FanDuel ingestion. Build CLV tracker. Build weekly report. Analyze results after 4 tournaments.

---

## Appendix B: First 10 Tickets

1. **FOUND-001:** Initialize repository with project structure, pyproject.toml, Makefile, and CI config.
2. **FOUND-002:** Design and implement database schema (all core tables) with SQLite and migration helpers.
3. **FOUND-003:** Implement config loading from settings.yaml, books.yaml, and .env with validation and typed access.
4. **DATA-001:** Build DataGolf API client — authenticate, fetch pre-tournament forecasts, store raw snapshots.
5. **DATA-002:** Build odds normalization module — American/decimal/implied-prob conversion, round-trip tests.
6. **DATA-003:** Build vig removal module — multiplicative and power methods, property-based tests.
7. **DATA-004:** Build DraftKings pre-tournament odds ingestion for matchup markets.
8. **PRICE-001:** Build matchup fair-odds pricing from DataGolf individual player probabilities.
9. **PRICE-002:** Build edge detection — compare fair prices vs. normalized book prices, rank by edge size.
10. **RISK-001:** Build fractional Kelly sizing with hard caps, per-golfer and per-tournament exposure limits.

---

## Appendix C: Skill Specs to Write as Separate Markdown Files

Each of these should be a standalone file in `docs/skills/`:

1. `datagolf-ingestion.md` — DataGolf API client skill spec
2. `sportsbook-ingestion.md` — Book odds fetching skill spec
3. `odds-normalization.md` — Odds format conversion skill spec
4. `vig-removal.md` — Hold/vig removal skill spec
5. `dead-heat-settlement.md` — Dead-heat and settlement rules skill spec
6. `player-resolution.md` — Player name/ID matching skill spec
7. `fair-odds-pricing.md` — Fair price calculation skill spec (matchups, 3-balls, top-N, outrights)
8. `edge-scoring.md` — Edge detection and ranking skill spec
9. `bankroll-sizing.md` — Kelly sizing and stake calculation skill spec
10. `exposure-control.md` — Concentration and correlation limits skill spec
11. `drawdown-management.md` — Drawdown brakes and stop conditions skill spec
12. `backtesting.md` — Walk-forward replay and evaluation skill spec
13. `clv-tracking.md` — Closing line value calculation skill spec
14. `reporting.md` — Report generation skill spec
15. `config-secrets.md` — Configuration and secrets management skill spec
16. `data-quality.md` — Data validation and anomaly detection skill spec
17. `orchestration.md` — Pipeline scheduling and coordination skill spec

---

## Appendix D: Suggested agent.md / Project Charter

```markdown
# UpAndDown: Project Charter

## What this is
A systematic golf edge-discovery and strategy-validation framework. DataGolf
provides the model. The system translates forecasts into fair prices, finds
daily edges against sportsbook lines, sizes bets conservatively, visualizes
backtest results, and tracks a bounded paper-bet sample to validate the
strategy.

## Philosophy
Survival first. No-bet is the default. Small repeatable edges in
matchup markets. Tiny convex sleeve for outrights. Never compromise
the bankroll.

Do not try to replace dedicated bet-tracking apps. Long-term real betting
history can be imported later; the MVP should focus on daily edges, backtests,
and paper proof.

## Current phase
Phase 0 — Foundation.

## Conventions
- Python 3.11+.
- All configurable values in settings.yaml or books.yaml.
- Secrets in .env, never committed.
- All modules have unit tests. Target 80%+ coverage on core modules.
- Every function that does math has property-based tests.
- No hardcoded magic numbers.
- Every bet decision is logged with full provenance.
- Use type hints. Use dataclasses for interfaces between modules.

## Module interfaces
Modules communicate via typed dataclasses:
- RawSnapshot, NormalizedOdds, FairPrice, BookPrice
- BetCandidate, BetTicket, PlacedBet, BetOutcome
- BankrollState, ExposureReport

## What not to do
- Do not build a custom golf model. Use DataGolf.
- Do not automate bet placement (Phase 1-4).
- Do not add markets, books, or tours before the matchup MVP works.
- Do not build a full betting-history tracker in MVP.
- Do not tune parameters on backtest results without a holdout set.
- Do not trust ROI over fewer than 100 bets. Use CLV.
- Do not override the risk engine. It has veto power.

## Key files
- config/settings.yaml — all parameters
- config/books.yaml — book-specific rules
- docs/adr/ — architecture decisions
- docs/skills/ — skill specs for each module
- src/ — all source code
- tests/ — all tests

## Build order
Foundation → Ingestion → Normalization → Pricing → Risk →
Paper Trading → Shadow Live → Small Capital → Iteration

## Success metric
Positive aggregate CLV over 50+ bets measured across 8+ tournaments.
```
