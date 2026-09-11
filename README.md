# PokerNow hand-history tool

Fetch, live-track or import [PokerNow](https://www.pokernow.com) hand histories, replay hands, and get per-player stats plus luck and position analysis, per session or across everything you have played. Python 3.11+, FastAPI, dependency-free web UI, CLI. Everything stays on your machine.

Simulated session, fictional players:

![Overview](docs/img/overview.png)

![Insights](docs/img/insights-luck.png)

## Quick start

macOS: double-click `PokerNow.command`. Elsewhere:

```bash
uv venv && uv pip install -e ".[dev]"
pokernow serve          # http://127.0.0.1:8000
```

Paste a game link, then *Track live* while you play or *Fetch* afterwards. No login needed. Archives land in `data/<gameId>/` (raw hands, log and ledger, plus `stats.json`, `players.csv`, `hands.csv` and `summary.md`). PokerNow deletes hands after 5 days; the archive keeps them.

You can also drop the replayer's `poker-now-hands-game-<id>.json` or the log CSV onto the home screen. Your own un-shown hole cards appear when PokerNow knows who you are: upload the log CSV you download while logged in, or paste your `npt` cookie under **?** in the header. The cookie stays in memory and never touches disk.

## What you get

**Stats.** VPIP, PFR, 3-bet, AF, WTSD, W$SD, c-bet, fold to c-bet, net, bb/100, and a cumulative net chart. Hands list with filters and a step-through replayer.

**Insights**, all deterministic (exact runout enumeration postflop, fixed-seed Monte Carlo preflop):

- *Your stats over the session*: VPIP, PFR, 3-bet, AF, c-bet, fold to c-bet, WTSD and won-when-saw-flop as running lines after each hand, with the rest of the table pooled as a dashed reference.
- *Showdown highlights*: got lucky (won from behind), bad beats (ahead when the money went in, lost) and coolers (an overpair, two pair or better, or JJ+/AK that beat 85% of all hands at that point and still lost), each with both five-card hands and a one-line verdict. Click one to replay it.
- *Luck as situations* (needs your hole cards): starting-hand strength, premium hands dealt, flop hits and flopped sets against their theoretical rates. Counted as frequencies, never chips.
- *Luck as money* (all players): each flop, turn and river card priced as the change in equity times the pot at that moment, from cards shown at showdown. Sums to zero across the table. Luck-adjusted net sits beside it, with every big pot lost sorted into outdrawn, cooler or other. The replayer ends each showdown with a "top X% of hands" strength line per player.
- *Position*: net in and out of position for every player who saw a flop.
- *Your game*: whole-hand paid and received by starting-hand group and by flop made hand.

**All my sessions.** Names change every night and IDs change with devices, but you are always identifiable, so one button merges every archive and upload where your player ID appears into one session with the same Overview and Insights. Other players merge by ID too, with earlier names shown as aka. Mark an ID that changed with the **Same person** control; those groups live in `data/identities.json` and never leave your machine.

## CLI and API

```bash
pokernow fetch <url>    pokernow live <url>    pokernow stats <file-or-archive>
pokernow hands <file-or-archive> --min-pot 500    pokernow hand <file-or-archive> 42
pokernow export <file-or-archive>    pokernow serve --port 8000
```

API docs at `/docs`. From Python: `parse_file`, `compute_session_stats`, `compute_insights`.

Tests: `.venv/bin/python -m pytest`. [MIT](LICENSE). Not affiliated with PokerNow.
