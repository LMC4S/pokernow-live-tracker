"""Everything you have played, merged into one session.

PokerNow keys players by ID and lets the display name change between
sit-downs, so a per-session view sees "AAs", "Jeff" and "老头" as three
strangers. Only one player is always identifiable, though: *you*. A session
knows its hero from the ``Your hand is`` lines of a logged-in log, or from
the export's ``playerId``. This module takes every session you have, works
out which player IDs are yours, renames them to one key, and concatenates
the hands so :func:`~pokernow.stats.compute_session_stats` and
:func:`~pokernow.insights.compute_insights` run unchanged over the lot.

Other players are merged by ID the same way (the ledger does this too), so a
regular with a new nickname every week is still one row. IDs that change
between sessions (new device, no login) stay separate — nothing in the data
links them, and guessing would be worse than a duplicate row — unless you say
so: ``merge_sessions(..., same=[[id, id, ...], ...])`` takes groups of IDs
that are one person (the app keeps them in ``identities.json``).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .models import Hand, Session
from .parser import _remap_session, _split_key

ME_ID = "me"
ME_NAME = "All my sessions"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class Source:
    """One session going into the merge, with a label for the report."""

    label: str  # game id, or the upload's file name
    session: Session
    game_id: str | None = None


@dataclass
class SourceReport:
    label: str
    game_id: str | None
    started_at: str | None
    hands: int
    big_blind: int | None
    included: bool
    you: str | None = None  # the name you played under in this session
    your_hands: int = 0
    your_net: int = 0
    reason: str | None = None  # why it was skipped

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Aggregate:
    session: Session | None
    hero_ids: list[str]
    sources: list[SourceReport]
    big_blinds: list[int] = field(default_factory=list)
    same: list[dict[str, Any]] = field(default_factory=list)  # manual "same person" groups, as applied

    def to_dict(self) -> dict[str, Any]:
        return {
            "hero": self.session.hero if self.session else None,
            "hero_ids": self.hero_ids,
            "hands": len(self.session.hands) if self.session else 0,
            "big_blinds": self.big_blinds,
            "sources": [s.to_dict() for s in self.sources],
            "same": self.same,
        }


def _rep_of(groups: list[list[str]]):
    """Union the manual groups; returns ``rep(pid)`` mapping every ID to its
    group's representative (itself when not in any group)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for g in groups:
        ids = [i for i in g if i]
        for other in ids[1:]:
            a, b = find(ids[0]), find(other)
            if a != b:
                parent[b] = a
    return lambda pid: find(pid) if pid in parent else pid


def _ts(t: datetime | None) -> datetime:
    t = t or _EPOCH
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _most_common(values: list[int]) -> int | None:
    if not values:
        return None
    counts: dict[int, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def hero_ids(sessions: list[Session]) -> set[str]:
    """Every player ID that is you: the hero of each session, plus any ID a
    mid-session ID change links to one of those (closed over all sessions)."""
    ids = {_split_key(s.hero)[1] for s in sessions if s.hero}
    ids.discard("")
    links = [(_split_key(a)[1], _split_key(b)[1]) for s in sessions for a, b in s.aliases.items()]
    changed = True
    while changed:
        changed = False
        for a, b in links:
            if a and b and (a in ids) != (b in ids):
                ids |= {a, b}
                changed = True
    return ids


def _keys_of(session: Session, is_mine) -> set[str]:
    out = set()
    for h in session.hands:
        for st in h.seats:
            if is_mine(_split_key(st.player)[1]):
                out.add(st.player)
    return out


def merge_sessions(sources: list[Source], same: list[list[str]] | None = None) -> Aggregate:
    """Merge every source where you can be identified into one session.

    Hands are deduplicated by PokerNow hand id (an uploaded log and a fetched
    archive of the same game overlap; the copy that knows your hole cards
    wins), ordered chronologically and renumbered. Every key of yours becomes
    ``<latest name> @ <latest id>``; other players collapse onto their ID
    with the latest name they used. Old keys are recorded as aliases so the
    UI can show "aka …". ``same`` lists groups of IDs that are one person
    (your say-so, for people who switched devices); a group containing one
    of your IDs is all you.
    """
    sessions = [s.session for s in sources]
    rep = _rep_of(same or [])
    ids = hero_ids(sessions)
    hero_reps = {rep(i) for i in ids}
    reports: list[SourceReport] = []
    if not ids:
        for src in sources:
            reports.append(_report(src, None, included=False, reason="no session identifies you"))
        return Aggregate(None, [], reports)

    def is_mine(pid: str) -> bool:
        return rep(pid) in hero_reps

    # collect hands, best copy per hand id
    picked: dict[str, tuple[Hand, str]] = {}
    ordered = sorted(sources, key=lambda s: _ts(s.session.started_at))
    for src in ordered:
        mine = _keys_of(src.session, is_mine)
        if not mine:
            reports.append(_report(src, None, included=False, reason="you did not play in this session"))
            continue
        reports.append(_report(src, mine, included=True))
        for h in src.session.hands:
            cur = picked.get(h.id)
            if cur is None or _richer(h, cur[0]):
                picked[h.id] = (h, src.label)

    hands: list[tuple[Hand, str]] = sorted(picked.values(), key=lambda hs: (_ts(hs[0].started_at), hs[0].number))
    merged = Session(source_name=ME_ID, source_format="aggregate")
    for n, (h, label) in enumerate(hands, start=1):
        c = copy.deepcopy(h)
        c.notes = [f"{label} · hand #{h.number}"] + [x for x in c.notes]
        c.number = n
        merged.hands.append(c)
    for src in ordered:
        merged.events.extend(copy.deepcopy(src.session.events))
        merged.unparsed.extend(src.session.unparsed)

    # canonical key per person (ID, or manual group): the latest name and ID
    # they played under; you get one key
    latest: dict[str, tuple[str, str]] = {}
    members: dict[str, dict[str, str]] = {}  # rep -> {key: name} seen, for the report
    hero_rep: str | None = None
    for h in merged.hands:  # chronological
        for st in h.seats:
            name, pid = _split_key(st.player)
            if pid:
                latest[rep(pid)] = (name, pid)
                members.setdefault(rep(pid), {})[st.player] = name
                if is_mine(pid):
                    hero_rep = rep(pid)
    hero_key = "%s @ %s" % latest[hero_rep] if hero_rep else None
    all_ids = sorted({pid for r in hero_reps for pid in (i for i in ids if rep(i) == r)} | {
        _split_key(k)[1] for r in hero_reps for k in members.get(r, {})})

    def canon(key: str) -> str:
        name, pid = _split_key(key)
        if hero_key and is_mine(pid):
            return hero_key
        ln, lp = latest.get(rep(pid), (None, None))
        new = f"{ln} @ {lp}" if ln else key
        return new if new != key else key

    seen: set[str] = set()
    for h in merged.hands:
        seen.update(st.player for st in h.seats)
        seen.update(a.player for a in h.actions)
        seen.update(h.known_cards)
    for e in merged.events:
        if e.player:
            seen.add(e.player)
    aliases = {k: canon(k) for k in seen if canon(k) != k}
    for src in ordered:  # in-session aliases, carried through the merge
        for old, new in src.session.aliases.items():
            if canon(new) != old:
                aliases[old] = canon(new)
    merged.aliases = aliases
    merged.hero = hero_key
    _remap_session(merged, canon)
    for h in merged.hands:
        if h.hero_cards and hero_key:
            h.hero = hero_key
            h.known_cards.setdefault(hero_key, h.hero_cards)

    bbs = sorted({h.big_blind for h in merged.hands if h.big_blind})
    applied = []
    for g in same or []:
        reps = {rep(i) for i in g if i}
        keys = sorted(k for r in reps for k in members.get(r, {}))
        if len({_split_key(k)[1] for k in keys}) < 2:
            continue  # nothing to merge (IDs not seen, or only one of them)
        applied.append({"ids": [i for i in g if i], "as": canon(keys[0]), "members": keys})
    return Aggregate(merged, all_ids, reports, bbs, applied)


def _richer(a: Hand, b: Hand) -> bool:
    """Is copy ``a`` of a hand more informative than copy ``b``?"""
    return (bool(a.hero_cards), len(a.known_cards), len(a.actions)) > (bool(b.hero_cards), len(b.known_cards), len(b.actions))


def _report(src: Source, mine: set[str] | None, *, included: bool, reason: str | None = None) -> SourceReport:
    s = src.session
    rep = SourceReport(
        label=src.label,
        game_id=src.game_id,
        started_at=s.started_at.isoformat() if s.started_at else None,
        hands=len(s.hands),
        big_blind=_most_common([h.big_blind for h in s.hands if h.big_blind]),
        included=included,
        reason=reason,
    )
    if mine:
        last_name = None
        for h in s.hands:
            for st in h.seats:
                if st.player in mine:
                    last_name = _split_key(st.player)[0]
            if any(p in mine for p in h.players):
                rep.your_hands += 1
                rep.your_net += sum(h.net(p) for p in mine if p in h.players)
        rep.you = last_name
    return rep
