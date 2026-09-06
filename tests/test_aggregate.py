"""Merging every session on the hero's player ID (aggregate.py + /api/me)."""

from pathlib import Path

from fastapi.testclient import TestClient

from pokernow.aggregate import Source, hero_ids, merge_sessions
from pokernow.app import create_app
from pokernow.insights import compute_insights
from pokernow.models import ActionType, Street
from pokernow.parser import parse_text
from pokernow.stats import compute_session_stats

FIXTURE = Path(__file__).parent / "fixtures" / "sample_log.csv"
TEXT = FIXTURE.read_text()


def _variant(*, rename: dict[str, str] | None = None, day: str = "2024-03-17", drop_hero: bool = False) -> str:
    """The fixture as a different night: new hand ids and timestamps, optional
    renames ("Alice @ aaa111" -> "Ally @ aaa111" keeps the ID; a new ID too)."""
    t = TEXT.replace("2024-03-10", day).replace("(id: h", f"(id: {day}-h")
    for old, new in (rename or {}).items():
        t = t.replace(old, new)
    if drop_hero:
        t = "\n".join(line for line in t.splitlines() if "Your hand is" not in line)
    return t


def _src(label: str, text: str) -> Source:
    return Source(label, parse_text(text, source_name=label), game_id=label)


def test_hero_ids_follow_in_session_id_changes():
    a = parse_text(TEXT, source_name="a")
    b = parse_text(_variant(drop_hero=True), source_name="b")
    b.aliases["Alice @ aaa111"] = "Alice @ newdev"  # a mid-session "player ID change"
    assert hero_ids([a, b]) == {"aaa111", "newdev"}


def test_merge_renames_hero_and_dedupes_hands():
    night1 = _src("g1", TEXT)
    night2 = _src("g2", _variant(rename={"Alice @ aaa111": "Ally @ aaa111", "Bob @ bbb222": "Robert @ bbb222"}))
    agg = merge_sessions([night2, night1])  # order in doesn't matter
    m = agg.session
    assert m is not None and m.hero == "Ally @ aaa111"  # latest name wins
    assert agg.hero_ids == ["aaa111"]
    assert [h.number for h in m.hands] == list(range(1, 13))  # renumbered in time order
    assert m.hands[0].notes[0] == "g1 · hand #1" and m.hands[6].notes[0] == "g2 · hand #1"
    assert m.aliases["Alice @ aaa111"] == "Ally @ aaa111" and m.aliases["Bob @ bbb222"] == "Robert @ bbb222"
    names = {p for h in m.hands for p in h.players}
    assert "Alice @ aaa111" not in names and "Bob @ bbb222" not in names
    # every hand still knows the hero's cards under the merged key
    assert all(h.hero == m.hero and h.known_cards.get(m.hero) == h.hero_cards for h in m.hands if h.hero_cards)

    stats = compute_session_stats(m)
    hero = next(p for p in stats.players if p.player == m.hero)
    one = next(p for p in compute_session_stats(night1.session).players if p.player == "Alice @ aaa111")
    assert hero.hands == 2 * one.hands and hero.net == 2 * one.net
    assert hero.aka == ["Alice"]

    reports = {r.label: r for r in agg.sources}
    assert reports["g1"].you == "Alice" and reports["g2"].you == "Ally"
    assert reports["g1"].your_hands == one.hands and reports["g1"].your_net == one.net
    assert all(r.included for r in agg.sources)

    # the same night twice (an upload next to its archive) counts once
    again = merge_sessions([night1, _src("copy", TEXT)])
    assert len(again.session.hands) == 6


def test_sessions_without_the_hero_are_skipped_but_id_matches_count():
    anon = _src("anon", _variant(drop_hero=True))  # no "Your hand is": no hero, but Alice's ID is there
    other = _src("other", _variant(day="2024-03-24", drop_hero=True,
                                   rename={"Alice @ aaa111": "Someone @ zzz999"}))
    agg = merge_sessions([_src("g1", TEXT), anon, other])
    by = {r.label: r for r in agg.sources}
    assert by["anon"].included and by["anon"].you == "Alice"
    assert not by["other"].included and "did not play" in by["other"].reason
    assert len(agg.session.hands) == 12

    nothing = merge_sessions([anon, other])
    assert nothing.session is None and all(not r.included for r in nothing.sources)


def test_insights_convert_blinds_per_hand():
    """A 5/10 night and a 10/20 night: bb totals add up hand by hand, not at
    the merged session's most common blind."""
    small = _src("g1", TEXT)
    big = _src("g2", _variant().replace("posts a small blind of 5", "posts a small blind of 10")
               .replace("posts a big blind of 10", "posts a big blind of 20"))
    assert {h.big_blind for h in big.session.hands if h.big_blind} == {20}
    m = merge_sessions([small, big]).session
    session_bb = compute_session_stats(m).big_blind
    ins = compute_insights(m, session_bb)
    hero = m.hero

    def played(h):
        return any(a.player == hero and a.type in (ActionType.CALL, ActionType.BET, ActionType.RAISE)
                   and a.street is Street.PREFLOP for a in h.actions)

    counted = [h for h in m.hands if hero in h.players and not h.bomb_pot and played(h)]
    assert counted
    per_hand = sum(h.net(hero) / h.big_blind for h in counted)
    at_session_bb = sum(h.net(hero) for h in counted) / session_bb
    got = sum(g["net_bb"] for g in ins["groups"].values())
    assert abs(got - per_hand) < 0.05 * len(ins["groups"]) + 1e-9
    assert abs(got - at_session_bb) > 0.5  # the naive conversion would be wrong here


def test_api_me(tmp_path):
    client = TestClient(create_app(str(tmp_path)))
    r = client.get("/api/me")
    assert r.status_code == 200 and r.json()["id"] is None and r.json()["sources"] == []
    assert client.post("/api/me/load").status_code == 404

    for name, text in (("night1.csv", TEXT), ("night2.csv", _variant(rename={"Alice @ aaa111": "Ally @ aaa111"}))):
        assert client.post("/api/sessions", files={"file": (name, text.encode(), "text/csv")}).status_code == 200

    r = client.post("/api/me/load")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "me" and body["summary"]["hands"] == 12
    assert body["aggregate"]["hero"] == "Ally @ aaa111"
    assert [s["label"] for s in body["aggregate"]["sources"]] == ["night1.csv", "night2.csv"]

    r = client.get("/api/sessions/me")
    assert r.json()["hero"] == "Ally @ aaa111" and r.json()["aggregate"]["hands"] == 12
    ins = client.get("/api/sessions/me/insights").json()
    assert ins["hero"] == "Ally @ aaa111" and ins["hero_dealt"] == 12
    assert client.get("/api/sessions/me/hands/7").json()["notes"][0] == "night2.csv · hand #1"

    # cached until a source changes
    assert client.get("/api/me").json()["hands"] == 12
    assert "me" in {s["id"] for s in client.get("/api/sessions").json()}


def test_manual_same_person_groups():
    night1 = _src("g1", TEXT)
    night2 = _src("g2", _variant(rename={"Bob @ bbb222": "Bobby @ newdev"}))
    plain = merge_sessions([night1, night2]).session
    assert {p for h in plain.hands for p in h.players if p.startswith("Bob")} == {"Bob @ bbb222", "Bobby @ newdev"}

    agg = merge_sessions([night1, night2], same=[["bbb222", "newdev"], ["ghost1", "ghost2"]])
    m = agg.session
    assert {p for h in m.hands for p in h.players if p.startswith("Bob")} == {"Bobby @ newdev"}
    assert m.aliases["Bob @ bbb222"] == "Bobby @ newdev"
    assert len(agg.same) == 1 and agg.same[0]["as"] == "Bobby @ newdev"
    assert agg.same[0]["members"] == ["Bob @ bbb222", "Bobby @ newdev"]
    bobby = next(p for p in compute_session_stats(m).players if p.player == "Bobby @ newdev")
    assert bobby.hands == 12 and bobby.aka == ["Bob"]

    # a group that touches one of your IDs is all you
    you = merge_sessions([night1, _src("g3", _variant(drop_hero=True, rename={"Alice @ aaa111": "Al @ phone1"}))],
                         same=[["aaa111", "phone1"]])
    assert you.session.hero == "Al @ phone1" and set(you.hero_ids) == {"aaa111", "phone1"}
    assert all(r.included for r in you.sources)


def test_api_identities(tmp_path):
    client = TestClient(create_app(str(tmp_path)))
    assert client.get("/api/identities").json()["same"] == []
    client.post("/api/sessions", files={"file": ("n1.csv", TEXT.encode(), "text/csv")})
    client.post("/api/sessions", files={"file": ("n2.csv", _variant(rename={"Bob @ bbb222": "Bobby @ newdev"}).encode(), "text/csv")})
    names = lambda: {p["name"] for p in client.post("/api/me/load").json()["summary"]["players"]}  # noqa: E731
    assert {"Bob", "Bobby"} <= names()
    r = client.put("/api/identities", json={"same": [["bbb222", "newdev"], ["only-one"]]})
    assert r.json()["same"] == [["bbb222", "newdev"]]
    assert (tmp_path / "identities.json").exists()
    assert "Bob" not in names() and "Bobby" in names()  # the merge picked the change up
