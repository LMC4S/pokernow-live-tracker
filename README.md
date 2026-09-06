# PokerNow hand-history tool

Fetch, live-track or import [PokerNow](https://www.pokernow.com) hand histories, replay hands, and compute per-player stats (VPIP, PFR, 3-bet, AF, WTSD, W$SD, c-bet, net, bb/100) plus deterministic luck and position analysis. Python 3.11+, FastAPI backend, dependency-free web UI, CLI.

## Screenshots

Simulated session, fictional players.

![Home screen](docs/img/home.png)

![Overview: summary cards, player stats, cumulative net](docs/img/overview.png)

![Hand list with the replayer open](docs/img/replayer.png)

![Insights: luck as situations and luck as money](docs/img/insights-luck.png)

## Quick start

macOS: double-click `PokerNow.command`. It creates the virtualenv on first run, starts the web UI and opens it. Data lands in `data/<gameId>/` next to the launcher.

Anywhere else:

```bash
uv venv && uv pip install -e ".[dev]"
pokernow serve          # http://127.0.0.1:8000
```

Paste a game link, then *Track live* while you play or *Fetch* afterwards. No PokerNow login needed.

## Getting a game in

**From the link.** `pokernow fetch <url>` pulls the ledger, every hand and the session log from PokerNow's own per-game endpoints. `pokernow live <url>` polls every 15 s and never writes a hand still in progress. Both refresh the same archive incrementally, dedupe by hand id, and write atomically, so live tracking and a later fetch fill gaps instead of duplicating. PokerNow allows about 2 requests per second, so a 450-hand session takes around 5 minutes the first time. PokerNow deletes hands after 5 days; the archive keeps them.

**From an export.** Drop the replayer's `poker-now-hands-game-<id>.json` or the ledger page's log CSV onto the home screen, or pass it to any CLI command. Stats from the JSON and the CSV of the same game match; given both, the tool merges them.

**Your own hole cards.** Table-wide data needs no login. Your un-shown hole cards appear only when PokerNow knows who you are. Either upload the log CSV you download while logged in (it contains your `Your hand is` lines), or paste your `npt` cookie in the web UI (**?** in the header; DevTools → Application → Cookies → `npt`). The cookie stays in server memory and never touches disk. `POKERNOW_NPT` in `.env` does the same for the CLI.

## Archive layout

```
data/<gameId>/
├─ poker-now-hands-game-<id>.json   raw hands
├─ poker_now_log_<id>.csv           raw session log
├─ ledger-<id>.json                 raw ledger
├─ meta.json                        fetch bookkeeping
├─ stats.json · players.csv         derived stats
├─ hands.csv                        one row per hand
└─ summary.md                       readable digest
```

Raw files are the source of truth. The tool regenerates derived files after every change; `pokernow export` rebuilds them on demand. Without the launcher, archives live in `~/.pokernow/games/` (override with `--data-dir` or `POKERNOW_DATA_DIR`).

## CLI

```bash
pokernow fetch  <game-url|id> [--no-log] [--data-dir DIR]
pokernow live   <game-url|id> [--interval 15]
pokernow export <file-or-archive-dir>
pokernow stats  <file-or-archive-dir> [--json]
pokernow hands  <file-or-archive-dir> --min-pot 500 --player Alice
pokernow hand   <file-or-archive-dir> 42
pokernow unparsed <file-or-archive-dir>
pokernow serve --port 8000
```

## API

Interactive docs at `/docs`. The main routes:

| Method | Path | Description |
|---|---|---|
| POST | `/api/fetch` | start a background fetch, returns a job |
| POST/GET/DELETE | `/api/live[/{gameId}]` | live tracking |
| GET | `/api/archives` · POST `/api/archives/{gameId}/load` | archived games |
| POST | `/api/sessions` | upload a `.csv` or `.json` |
| GET | `/api/sessions/{id}` | summary and player stats |
| GET | `/api/sessions/{id}/hands[/{n}]` | hand summaries, or one full hand |
| GET | `/api/sessions/{id}/insights` | everything on the Insights tab |

## Library

```python
from pokernow.parser import parse_file, load_archive
from pokernow.stats import compute_session_stats
from pokernow.insights import compute_insights

session = parse_file("game.json")            # or .csv, or load_archive("data/<id>")
stats = compute_session_stats(session)
ins = compute_insights(session, stats.big_blind)
```

## What the parsers understand

CSV log: hand start/end (old and new formats, dead button), stacks, hero cards, blinds, straddles, antes, bomb pots, every action including `and go all in` (amounts are street totals, as PokerNow logs them), run-it-twice and double boards, rabbit hunts, uncalled bets, collects with hand descriptions, shows, and table events (join, quit, stand up, rebuy, admin stack changes, player ID changes, config changes). The parser keeps unknown lines and shows them under `unparsed`.

Hands JSON: `handVersion 2`, every event type in PokerNow's enum, bomb pots, double boards, run-it-twice, rake, and `playerNet` as a cross-check against the parsed hero net.

Tests check chip conservation (`collected + rake == pot`) and flag any hand that breaks it as `chip_mismatch`.

## Stat definitions

- **VPIP**: put chips in preflop voluntarily. Blinds, straddles and bomb-pot posts don't count.
- **PFR**: raised preflop. **3-Bet%**: re-raised when facing one raise, over opportunities.
- **AF**: (bets + raises) / calls, all streets.
- **WTSD%**: showdowns / flops seen. **W$SD%**: showdowns won / showdowns.
- **C-Bet%**: preflop aggressor bet the flop first. **Fold→CB%**: folded to it.
- **Net, Net(bb), bb/100**: chips won minus chips put in, uncalled bets excluded.

## Insights

Everything in `src/pokernow/insights.py` is deterministic, so it recomputes live and gives the same answer each run. Equity uses exact runout enumeration once a flop is out and a fixed-seed 2,000-iteration Monte Carlo preflop. Tests cross-check the 7-card evaluator against a brute-force reference on 80k random hands.

Luck splits into two channels that share no unit, so the tab never adds them.

**Luck · situations (hero only).** How often good things happened: starting-hand strength vs a random deal (z-test), premium categories dealt vs their exact probabilities (binomial p), flop hit rate and flopped sets vs expectation. Scored as frequencies, never as chips, because pricing a flopped set would mean guessing how the betting would have gone. Nine tests run side by side, so one lit badge per session is what chance produces; badges light only beyond |z| ≈ 2.

**Luck · money (all players).** For each showdown with known cards and a single-run board, each street's card is priced on the money already in the middle:

```
luck = (eq_flop − eq_pre)  × pot before the flop
     + (eq_turn − eq_flop) × pot before the turn
     + (eq_river − eq_turn) × pot before the river
```

A rivered gutshot after a tiny turn call scores tiny luck; the big river bet you then win is payoff. Luck sums to zero across the table. **Luck-adj net** is net minus money luck, nothing more. **Setups** counts showdowns lost for 40 bb or more while holding top pair or better when the money went in; it covers both beats and coolers, and overlaps money luck, so compare the two rather than subtracting. Limits: folds to scare cards go unscored, side pots are ignored, run-it-twice and double-board hands are excluded, and mucked showdowns are invisible.

**Position.** Among players who saw the flop, the one acting last is IP, the rest OOP. Net per player-hand, for every player. Read it as a ledger: the OOP pool carries the blind tax and forced defends, so everyone looks better IP. Judge a player's OOP number against the table's, not against zero.

**Money flow.** Each pot's losses split among its winners by share. The UI shows the largest net pipelines between two players and hides those under 5 bb. Rebuilt nets match PokerNow's ledger to the chip.

**Your game (hero only).** Two whole-hand ledgers, paid vs received, with totals that reconcile to session net: by starting-hand group (TT+/AK/AQs, small pairs, two broadway, everything else) and by flop made hand (two pair+, top pair or overpair, weak pair, no pair).

The tab does not estimate opponents' frequency luck (their folded and mucked hands are unobservable), judge implied-odds calls, or measure tilt.

## Tests

```bash
.venv/bin/python -m pytest
```

Fetch tests stub HTTP; nothing hits the network.

## Privacy

Everything stays on your machine. The only outbound requests go to PokerNow's public per-game endpoints, paced at its rate limit. Treat the `npt` cookie like a password.

## License

[MIT](LICENSE). Independent community tool, not affiliated with PokerNow.
