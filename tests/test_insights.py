"""Tests for the deterministic insights module (evaluator, equity, session stats)."""

import itertools
import json
import random
from collections import Counter

from pokernow.insights import (
    NULL_MEAN,
    PRE_EQ,
    card_int,
    cards_int,
    class_combos,
    compute_insights,
    equities,
    eval7,
    hand_class,
    hand_group,
    hand_luck,
    hand_percentile,
    _cooler_hand,
)
from pokernow.parser import parse_text


# ---------------------------------------------------------------------------
# evaluator
# ---------------------------------------------------------------------------

def _ref_eval5(cards):
    ranks = sorted((c >> 2 for c in cards), reverse=True)
    suits = [c & 3 for c in cards]
    flush = len(set(suits)) == 1
    rs = sorted(set(ranks), reverse=True)
    sh = -1
    if len(rs) == 5:
        if rs[0] - rs[4] == 4:
            sh = rs[0]
        elif rs == [12, 3, 2, 1, 0]:
            sh = 3
    cnt = Counter(ranks)
    groups = sorted(cnt.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    if sh >= 0 and flush:
        return (8, sh)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, *ranks)
    if sh >= 0:
        return (4, sh)
    if groups[0][1] == 3:
        k = [r for r in ranks if r != groups[0][0]]
        return (3, groups[0][0], *k)
    if groups[0][1] == 2 and groups[1][1] == 2:
        k = [r for r in ranks if cnt[r] == 1]
        return (2, groups[0][0], groups[1][0], *k)
    if groups[0][1] == 2:
        k = [r for r in ranks if r != groups[0][0]]
        return (1, groups[0][0], *k)
    return (0, *ranks)


def _ref_eval7(cards):
    return max(_ref_eval5(c) for c in itertools.combinations(cards, 5))


def cs(*names):
    return [card_int(n) for n in names]


def test_eval7_matches_reference_on_random_hands():
    rng = random.Random(7)
    for _ in range(2000):
        cards = rng.sample(range(52), 7)
        assert eval7(cards) == _ref_eval7(cards), cards


def test_eval7_known_hands():
    assert eval7(cs("As", "Ks", "Qs", "Js", "Ts", "2d", "3c"))[0] == 8  # royal-ish SF
    assert eval7(cs("Ah", "2s", "3s", "4s", "5s", "9d", "9c"))[0:2] == (4, 3)  # wheel straight
    assert eval7(cs("Ah", "Ad", "Ac", "Kh", "Kd", "2s", "3s")) == (6, 12, 11)  # aces full
    # two trips make a full house of the higher trips
    assert eval7(cs("Ah", "Ad", "Ac", "2h", "2d", "2c", "9s")) == (6, 12, 0)
    # flush beats straight
    assert eval7(cs("2h", "4h", "6h", "8h", "Th", "9s", "Jc"))[0] == 5


def test_hand_class_and_groups():
    assert hand_class(cs("As", "Ks")) == "AKs"
    assert hand_class(cs("Kd", "As")) == "AKo"
    assert hand_class(cs("7c", "7d")) == "77"
    assert hand_group("AA") == "strong"
    assert hand_group("AQs") == "strong"
    assert hand_group("AQo") == "broadway"
    assert hand_group("77") == "pairs_small"
    assert hand_group("QTo") == "broadway"
    assert hand_group("A9s") is None


def test_pre_eq_table_complete_and_centred():
    assert len(PRE_EQ) == 169
    assert sum(class_combos(c) for c in PRE_EQ) == 1326
    assert abs(NULL_MEAN - 0.5) < 0.005
    assert PRE_EQ["AA"] > 0.8 and PRE_EQ["72o"] < 0.4


def test_equities_river_and_turn():
    # river: made flush vs top pair -> 100 / 0
    eq = equities([cs("Ah", "Kh"), cs("As", "Ad")], cs("2h", "7h", "9h", "3c", "3d"))
    assert eq == [1.0, 0.0]
    # turn: set vs flush draw; probabilities sum to 1 and favourite is the set
    eq = equities([cs("7s", "7d"), cs("Ah", "Kh")], cs("7h", "2h", "9c", "3s"))
    assert abs(sum(eq) - 1.0) < 1e-9
    assert eq[0] > 0.7


# ---------------------------------------------------------------------------
# session-level insights on a tiny synthetic game
# ---------------------------------------------------------------------------

A = {"id": "aaa111", "seat": 1, "name": "Alice"}
B = {"id": "bbb222", "seat": 2, "name": "Bob"}


def _ev(at, **payload):
    return {"at": at, "payload": payload}


def _session_json():
    t = 1710100000000
    hands = [
        {
            # Bob open-raises, Alice calls with AA; all-in on the flop; Alice's
            # kings-up loses to a rivered straight. Showdown with both known.
            "id": "h1", "handVersion": 2, "number": "1", "gameType": "th", "cents": False,
            "smallBlind": 5, "bigBlind": 10, "ante": None, "straddleSeat": None, "dealerSeat": 1,
            "startedAt": t, "bombPot": False, "doubleBoard": None,
            "players": [dict(A, stack=500, hand=["Ah", "Ad"]), dict(B, stack=500)],
            "events": [
                _ev(t + 1, type=3, seat=1, value=5),
                _ev(t + 2, type=2, seat=2, value=10),
                _ev(t + 3, type=8, seat=1, value=30),
                _ev(t + 4, type=7, seat=2, value=30),
                _ev(t + 5, type=9, turn=1, run=1, cards=["Kh", "Qd", "2c"]),
                _ev(t + 6, type=1, seat=2, value=470, allIn=True),
                _ev(t + 7, type=7, seat=1, value=470, allIn=True),
                _ev(t + 8, type=9, turn=2, run=1, cards=["3d"]),
                _ev(t + 9, type=9, turn=3, run=1, cards=["Ts"]),
                _ev(t + 10, type=15),
                _ev(t + 11, type=12, seat=2, cards=["Ac", "Jc"]),
                _ev(t + 12, type=10, pot=1000, seat=2, value=1000, cards=["Ac", "Jc"],
                    combination=["Ac", "Kh", "Qd", "Jc", "Ts"], handDescription="Straight, A High",
                    position=2, runNumber="1", hiLo="h"),
            ],
        },
        {
            # Alice folds 72o preflop to a raise; Bob takes the blinds.
            "id": "h2", "handVersion": 2, "number": "2", "gameType": "th", "cents": False,
            "smallBlind": 5, "bigBlind": 10, "ante": None, "straddleSeat": None, "dealerSeat": 2,
            "startedAt": t + 60000, "bombPot": False, "doubleBoard": None,
            "players": [dict(A, stack=30, hand=["7h", "2d"]), dict(B, stack=970)],
            "events": [
                _ev(t + 60001, type=3, seat=2, value=5),
                _ev(t + 60002, type=2, seat=1, value=10),
                _ev(t + 60003, type=8, seat=2, value=30),
                _ev(t + 60004, type=11, seat=1),
                _ev(t + 60005, type=16, seat=2, value=20),
                _ev(t + 60006, type=10, pot=25, seat=2, value=25),
            ],
        },
    ]
    return json.dumps({"playerId": "aaa111", "gameId": "g1", "hands": hands})


def test_compute_insights_end_to_end():
    session = parse_text(_session_json(), source_name="test.json")
    ins = compute_insights(session, big_blind=10)

    assert ins["hero"] and ins["hero"].startswith("Alice")
    assert ins["hero_dealt"] == 2
    assert ins["hero_cards_known"] == 2

    q = ins["quality"]
    assert q["n"] == 2
    # AA + 72o were dealt
    assert dict(q["top_classes"]) == {"AA": 1, "72o": 1}
    assert next(c for c in q["categories"] if c["name"] == "AA")["observed"] == 1
    # AA was played, 72o folded
    assert q["played_mean_eq"] == PRE_EQ["AA"]
    assert q["folded_mean_eq"] == PRE_EQ["72o"]

    # luck: hand 1 is a measured showdown; Alice was a big favourite on the
    # flop and lost the pot, so her luck is deeply negative and Bob's mirrors it.
    alice = next(v for k, v in ins["luck"].items() if k.startswith("Alice"))
    bob = next(v for k, v in ins["luck"].items() if k.startswith("Bob"))
    assert alice["measured"] == bob["measured"] == 1
    assert alice["luck"] < -700
    assert alice["luck"] + bob["luck"] == 0  # luck is zero-sum when all survivors are known
    assert alice["allin_n"] == 1
    assert alice["adjusted_net"] == alice["net"] - alice["luck"]
    # Alice lost 50 bb as the favourite when the money went in: an outdraw,
    # not a cooler.
    assert alice["big_loss"]["outdrawn"] == {"n": 1, "chips": -500}
    assert alice["big_loss"]["cooler"]["n"] == alice["big_loss"]["other"]["n"] == 0
    assert all(v["n"] == 0 for v in bob["big_loss"].values())

    # whole-hand ledger by starting hand: AA played (strong) — paid 500 in
    # total, received 0, net -500; 72o dealt & folded (other)
    g = ins["groups"]
    assert g["strong"]["dealt"] == 1 and g["strong"]["played"] == 1
    assert g["strong"]["paid"] == 500 and g["strong"]["received"] == 0
    assert g["strong"]["net"] == -500 and g["strong"]["bb_per_hand"] == -50.0
    assert g["other"]["dealt"] == 1 and g["other"]["played"] == 0

    # same ledger by flop strength: AA is an overpair on Kh Qd 2c -> top_pair
    fs = ins["flop_strength"]
    assert fs["top_pair"] == {"hands": 1, "paid": 500, "received": 0, "net": -500,
                              "net_bb": -50.0, "bb_per_hand": -50.0}
    assert fs["two_pair_plus"]["hands"] == 0

    # table-wide position: hand 1's flop was seen by both; dealer Alice acts last
    pt = ins["position_table"]
    assert pt["ip"]["hands"] == 1 and pt["ip"]["net"] == -500
    assert pt["oop"]["hands"] == 1 and pt["oop"]["net"] == 500
    pp_alice = next(v for k, v in ins["position_players"].items() if k.startswith("Alice"))
    assert pp_alice["ip"] == {"hands": 1, "net": -500, "net_bb": -50.0, "bb_per_hand": -50.0}
    assert pp_alice["oop"]["hands"] == 0


def test_card_luck_uses_pot_at_reveal_not_final_pot():
    """A miracle river after calling a tiny bet is only a little luck: the big
    river bet won afterwards is payoff, not luck. Alice rivers a straight
    (gutshot, ~4/44 on the turn) in a 60-chip pot, then wins a 500 river bet."""
    t = 1710100000000
    hand = {
        "id": "h3", "handVersion": 2, "number": "1", "gameType": "th", "cents": False,
        "smallBlind": 5, "bigBlind": 10, "ante": None, "straddleSeat": None, "dealerSeat": 1,
        "startedAt": t, "bombPot": False, "doubleBoard": None,
        "players": [dict(A, stack=1000, hand=["5h", "6h"]), dict(B, stack=1000)],
        "events": [
            _ev(t + 1, type=3, seat=1, value=5),
            _ev(t + 2, type=2, seat=2, value=10),
            _ev(t + 3, type=7, seat=1, value=10),
            _ev(t + 4, type=0, seat=2),
            _ev(t + 5, type=9, turn=1, run=1, cards=["Kh", "8s", "2d"]),
            _ev(t + 6, type=0, seat=2), _ev(t + 7, type=0, seat=1),
            _ev(t + 8, type=9, turn=2, run=1, cards=["4s"]),
            _ev(t + 9, type=1, seat=2, value=20),          # tiny turn bet
            _ev(t + 10, type=7, seat=1, value=20),         # Alice calls with the gutshot
            _ev(t + 11, type=9, turn=3, run=1, cards=["7c"]),  # rivered straight
            _ev(t + 12, type=1, seat=1, value=500),
            _ev(t + 13, type=7, seat=2, value=500),
            _ev(t + 14, type=15),
            _ev(t + 15, type=12, seat=2, cards=["Kd", "Qd"]),
            _ev(t + 16, type=10, pot=1060, seat=1, value=1060, cards=["5h", "6h"],
                combination=["4s", "5h", "6h", "7c", "8s"], handDescription="Straight, 8 High",
                position=1, runNumber="1", hiLo="h"),
        ],
    }
    session = parse_text(json.dumps({"playerId": "aaa111", "gameId": "g2", "hands": [hand]}),
                         source_name="t.json")
    ins = compute_insights(session, big_blind=10)
    alice = next(v for k, v in ins["luck"].items() if k.startswith("Alice"))
    # she won a 1060 pot, but the river fell on a 60-chip pot: the river's luck
    # is ~(1 − eq_turn) × 60 ≈ +55, plus small flop/turn terms — nowhere near
    # the 530 that final-pot-based accounting would credit her with
    assert alice["net"] == 530
    assert 0 < alice["luck"] < 110
    bob = next(v for k, v in ins["luck"].items() if k.startswith("Bob"))
    assert alice["luck"] + bob["luck"] == 0


def test_insights_without_hero_cards():
    raw = json.loads(_session_json())
    raw["playerId"] = None
    for h in raw["hands"]:
        for p in h["players"]:
            p.pop("hand", None)
    session = parse_text(json.dumps(raw), source_name="anon.json")
    session.hero = None
    ins = compute_insights(session, big_blind=10)
    assert ins["quality"] is None
    # only Bob's hand was revealed at showdown, so no luck can be measured —
    # but the showdown is surfaced as unmeasured for both survivors
    alice = next(v for k, v in ins["luck"].items() if k.startswith("Alice"))
    assert alice["measured"] == 0
    assert alice["unmeasured_n"] == 1
    assert alice["unmeasured_net"] == -500


def _cooler_json():
    """Alice's middle set (TT on Q-T-5) stacks off into Bob's top set."""
    t = 1710200000000
    hand = {
        "id": "c1", "handVersion": 2, "number": "1", "gameType": "th", "cents": False,
        "smallBlind": 5, "bigBlind": 10, "ante": None, "straddleSeat": None, "dealerSeat": 1,
        "startedAt": t, "bombPot": False, "doubleBoard": None,
        "players": [dict(A, stack=500, hand=["Ts", "Tc"]), dict(B, stack=500)],
        "events": [
            _ev(t + 1, type=3, seat=1, value=5),
            _ev(t + 2, type=2, seat=2, value=10),
            _ev(t + 3, type=8, seat=1, value=30),
            _ev(t + 4, type=7, seat=2, value=30),
            _ev(t + 5, type=9, turn=1, run=1, cards=["Qh", "Td", "5c"]),
            _ev(t + 6, type=1, seat=2, value=470, allIn=True),
            _ev(t + 7, type=7, seat=1, value=470, allIn=True),
            _ev(t + 8, type=9, turn=2, run=1, cards=["3d"]),
            _ev(t + 9, type=9, turn=3, run=1, cards=["8s"]),
            _ev(t + 10, type=15),
            _ev(t + 11, type=12, seat=2, cards=["Qs", "Qc"]),
            _ev(t + 12, type=10, pot=1000, seat=2, value=1000, cards=["Qs", "Qc"],
                combination=["Qs", "Qc", "Qh", "Td", "Tc"], handDescription="Full House, Q Full of T",
                position=2, runNumber="1", hiLo="h"),
        ],
    }
    return json.dumps({"playerId": "aaa111", "gameId": "g2", "hands": [hand]})


def test_set_under_set_is_a_cooler_not_bad_luck():
    session = parse_text(_cooler_json(), source_name="cooler.json")
    ins = compute_insights(session, big_blind=10)
    alice = next(v for k, v in ins["luck"].items() if k.startswith("Alice"))
    # the deck barely moved: she was behind from the flop on
    assert -100 < alice["luck"] < 0
    assert alice["big_loss"]["cooler"] == {"n": 1, "chips": -500}
    assert alice["big_loss"]["outdrawn"]["n"] == alice["big_loss"]["other"]["n"] == 0

    per_hand = hand_luck(session.hands[0], 10)
    a = next(v for k, v in per_hand.items() if k.startswith("Alice"))
    b = next(v for k, v in per_hand.items() if k.startswith("Bob"))
    assert a["commit"] == b["commit"] == "flop"
    assert a["kind"] == "cooler" and b["kind"] is None
    # middle set beats everything but the three combos of QQ (Gambit's "top X%")
    assert a["pct"] > 0.99 and b["pct"] == 1.0


def test_hand_percentile():
    # preflop: AA is the top of the deck, 72o near the bottom, ties split
    assert hand_percentile(cs("As", "Ad"), []) > 0.99
    assert hand_percentile(cs("7s", "2d"), []) < 0.05
    # flop: top pair top kicker on a dry board beats nearly everything, an
    # unpaired ace-high only the unpaired hands below it
    board = cs("Kh", "7d", "2c")
    assert hand_percentile(cs("Ad", "Kc"), board) > 0.9
    assert 0.4 < hand_percentile(cs("Ad", "Qc"), board) < 0.7
    # cooler-grade hands: overpair / two pair+ yes, bare top pair no
    assert _cooler_hand(cs("Ad", "Ac"), board) and _cooler_hand(cs("Kd", "7c"), board)
    assert not _cooler_hand(cs("Ad", "Kc"), board)


def test_evolution_blocks():
    from pokernow.insights import compute_evolution
    from pokernow.models import Hand, SeatInfo, Action, Street, ActionType
    from datetime import datetime, timedelta

    hero, villain = "A @ a1", "B @ b1"
    hands = []
    for i in range(250):
        # a 4-hour gap before hand 200 starts a new sitting
        at = datetime(2026, 1, 1) + timedelta(minutes=i) + (timedelta(hours=4) if i >= 200 else timedelta())
        h = Hand(number=i + 1, id=f"h{i}", game_type="NLH", dealer=hero, started_at=at)
        h.seats = [SeatInfo(seat=1, player=hero, stack=1000), SeatInfo(seat=2, player=villain, stack=1000)]
        h.small_blind, h.big_blind = 10, 20
        if i % 2 == 0:  # hero raises every other hand and takes the blinds, folds the rest
            h.actions = [Action(player=villain, type=ActionType.SMALL_BLIND, amount=10, street=Street.PREFLOP),
                         Action(player=hero, type=ActionType.BIG_BLIND, amount=20, street=Street.PREFLOP),
                         Action(player=hero, type=ActionType.RAISE, amount=60, street=Street.PREFLOP),
                         Action(player=villain, type=ActionType.FOLD, street=Street.PREFLOP),
                         Action(player=hero, type=ActionType.UNCALLED_RETURN, amount=40, street=Street.PREFLOP),
                         Action(player=hero, type=ActionType.COLLECT, amount=30, street=Street.PREFLOP)]
        else:
            h.actions = [Action(player=hero, type=ActionType.SMALL_BLIND, amount=10, street=Street.PREFLOP),
                         Action(player=villain, type=ActionType.BIG_BLIND, amount=20, street=Street.PREFLOP),
                         Action(player=hero, type=ActionType.FOLD, street=Street.PREFLOP),
                         Action(player=villain, type=ActionType.COLLECT, amount=20, street=Street.PREFLOP)]
        hands.append(h)

    ev = compute_evolution(hands, hero)
    assert ev["hands"] == 250
    w = ev["windows"]["100"]
    # a bell window with 100 effective hands spans 163, moved 5 at a time, the last point reaching hand 250
    assert w["size"] == 100 and w["step"] == 5 and w["span"] == 163
    assert w["idx"][0] == 81 and w["idx"][-1] == 250 - 1 - 81 and w["n"] == len(w["idx"])
    assert all(abs(v - 50.0) < 1.0 for v in w["stats"]["vpip"])  # alternating raise/fold
    assert ev["breaks"] == [200] and ev["break_labels"] == ["1/1"]
    assert "200" not in ev["windows"]  # 250 hands is less than two windows of 200
    assert ev["big_pots"] == []


def test_evolution_big_pots_and_net():
    from pokernow.insights import compute_evolution, BIG_POT_BB
    from pokernow.models import Hand, SeatInfo, Action, Street, ActionType
    from datetime import datetime, timedelta

    hero, villain = "A @ a1", "B @ b1"
    hands = []
    big_at = {60, 65, 150}  # 65 is too soon after 60 to start a new segment
    for i in range(240):
        h = Hand(number=i + 1, id=f"h{i}", game_type="NLH", dealer=hero, started_at=datetime(2026, 1, 1) + timedelta(minutes=i))
        h.seats = [SeatInfo(seat=1, player=hero, stack=10000), SeatInfo(seat=2, player=villain, stack=10000)]
        h.small_blind, h.big_blind = 10, 20
        if i in big_at:  # hero wins a 120 bb pot
            h.actions = [Action(player=villain, type=ActionType.SMALL_BLIND, amount=10, street=Street.PREFLOP),
                         Action(player=hero, type=ActionType.BIG_BLIND, amount=20, street=Street.PREFLOP),
                         Action(player=villain, type=ActionType.RAISE, amount=2400, street=Street.PREFLOP),
                         Action(player=hero, type=ActionType.CALL, amount=2380, street=Street.PREFLOP),
                         Action(player=hero, type=ActionType.COLLECT, amount=4800, street=Street.SHOWDOWN)]
            h.contributions, h.collected = {hero: 2400, villain: 2400}, {hero: 4800}
        else:
            h.actions = [Action(player=hero, type=ActionType.SMALL_BLIND, amount=10, street=Street.PREFLOP),
                         Action(player=villain, type=ActionType.BIG_BLIND, amount=20, street=Street.PREFLOP),
                         Action(player=hero, type=ActionType.FOLD, street=Street.PREFLOP),
                         Action(player=villain, type=ActionType.COLLECT, amount=20, street=Street.PREFLOP)]
            h.contributions, h.collected = {hero: 10, villain: 20}, {villain: 30}
        hands.append(h)

    assert BIG_POT_BB == 100
    ev = compute_evolution(hands, hero)
    assert [p["number"] for p in ev["big_pots"]] == [61, 66, 151]
    assert ev["big_pots"][0] == {"i": 60, "number": 61, "net_bb": 120.0}
    w = ev["windows"]["100"]
    # every point sees at least one 120 bb pot inside its 163-hand span, so all are positive,
    # and the first (centred on hand 82, both early pots close by) is the highest
    assert all(v > 0 for v in w["net100"]) and w["net100"][0] == max(w["net100"])
    assert w["cum"][0] == round(sum(-0.5 if i not in big_at else 120 for i in range(82)), 1)


def _muck_json():
    """Hand 1 of `_session_json` (Alice's AA all in on the flop, outdrawn by
    Bob's shown AJ) plus a hand Alice wins at showdown where Bob mucks: Alice
    bets the river with top pair, Bob calls and does not show."""
    raw = json.loads(_session_json())
    t = 1710100000000 + 120000
    raw["hands"].append({
        "id": "h3", "handVersion": 2, "number": "3", "gameType": "th", "cents": False,
        "smallBlind": 5, "bigBlind": 10, "ante": None, "straddleSeat": None, "dealerSeat": 1,
        "startedAt": t, "bombPot": False, "doubleBoard": None,
        "players": [dict(A, stack=500, hand=["Ks", "Qs"]), dict(B, stack=500)],
        "events": [
            _ev(t + 1, type=3, seat=1, value=5),
            _ev(t + 2, type=2, seat=2, value=10),
            _ev(t + 3, type=8, seat=1, value=30),
            _ev(t + 4, type=7, seat=2, value=30),
            _ev(t + 5, type=9, turn=1, run=1, cards=["Kh", "7d", "2c"]),
            _ev(t + 6, type=1, seat=2, value=40),
            _ev(t + 7, type=7, seat=1, value=40),
            _ev(t + 8, type=9, turn=2, run=1, cards=["3d"]),
            _ev(t + 9, type=1, seat=2, value=100),
            _ev(t + 10, type=7, seat=1, value=100),
            _ev(t + 11, type=9, turn=3, run=1, cards=["9s"]),
            _ev(t + 12, type=1, seat=2, value=200),
            _ev(t + 13, type=7, seat=1, value=200),
            _ev(t + 14, type=15),
            _ev(t + 15, type=12, seat=1, cards=["Ks", "Qs"]),
            _ev(t + 16, type=10, pot=740, seat=1, value=740, cards=["Ks", "Qs"],
                combination=["Ks", "Kh", "Qs", "9s", "7d"], handDescription="Pair, K's",
                position=1, runNumber="1", hiLo="h"),
        ],
    })
    return json.dumps(raw)


def test_money_luck_separates_allin_from_mucked_showdowns():
    """Losers muck, so a hero's won showdowns mostly go unscored while every
    lost one is scored. The shown-hand total therefore drifts negative for the
    hero no matter what the deck did; the all-in slice is scored whoever won
    and is the number to compare players on."""
    session = parse_text(_muck_json(), source_name="muck.json")
    ins = compute_insights(session, big_blind=10)
    alice = next(v for k, v in ins["luck"].items() if k.startswith("Alice"))
    bob = next(v for k, v in ins["luck"].items() if k.startswith("Bob"))

    # the won showdown is unscored for both survivors (Bob mucked)...
    assert alice["measured"] == bob["measured"] == 1
    assert alice["unmeasured_n"] == bob["unmeasured_n"] == 1
    assert alice["unmeasured_net"] == 370 and bob["unmeasured_net"] == -370
    # ...so shown-hand luck is just the lost all-in: deeply negative for Alice
    assert alice["luck"] < -700 and alice["luck"] + bob["luck"] == 0
    # the all-in slice is complete: nothing was all in and left unscored
    assert alice["allin_n"] == bob["allin_n"] == 1
    assert alice["allin_unmeasured_n"] == bob["allin_unmeasured_n"] == 0
    assert alice["allin_luck"] == alice["luck"]
    assert alice["allin_adjusted_net"] == alice["net"] - alice["allin_luck"]
    assert alice["net"] == -500 - 10 + 370  # h1 lost, h2 blind folded, h3 won
    # the unscored won hand is visible as money, not silently dropped
    assert alice["unmeasured_net"] > 0 > bob["unmeasured_net"]


def _rit_json(run2_turn, run2_river, run2_winner_seat):
    """Hand 1 of _session_json (AA vs AJs, all in on the flop) run twice: the
    first run is the original 3d Ts, the second run's turn and river given."""
    raw = json.loads(_session_json())
    h = raw["hands"][0]
    h["id"] = f"h1-rit-{run2_turn}{run2_river}-{run2_winner_seat}"  # the luck cache is keyed by hand id
    t = h["startedAt"]
    h["events"] = [e for e in h["events"] if e["payload"].get("type") not in (9, 10)] + [
        _ev(t + 5, type=9, turn=1, run=1, cards=["Kh", "Qd", "2c"]),
        _ev(t + 8, type=9, turn=2, run=1, cards=["3d"]),
        _ev(t + 9, type=9, turn=3, run=1, cards=["Ts"]),
        _ev(t + 8, type=9, turn=2, run=2, cards=[run2_turn]),
        _ev(t + 9, type=9, turn=3, run=2, cards=[run2_river]),
        # each run pays out half the pot
        _ev(t + 12, type=10, pot=1000, seat=2, value=500, cards=["Ac", "Jc"], position=2, runNumber="1", hiLo="h"),
        _ev(t + 13, type=10, pot=1000, seat=run2_winner_seat, value=500, position=1, runNumber="2", hiLo="h"),
    ]
    h["events"].sort(key=lambda e: e["at"])
    return json.dumps(raw)


def test_run_it_twice_allin_is_scored_per_run():
    """A run-it-twice all-in showdown is scored: the flop (shared by both
    runs) rides on the whole pot, each run's turn and river on half of it.
    The hand counts as one all-in showdown, not as an unscored one."""
    session = parse_text(_rit_json("4d", "5s", 1), source_name="rit.json")
    h = session.hands[0]
    assert len(h.board_runs) == 2 and h.run_it_twice
    ins = compute_insights(session, big_blind=10)
    alice = next(v for k, v in ins["luck"].items() if k.startswith("Alice"))
    bob = next(v for k, v in ins["luck"].items() if k.startswith("Bob"))
    assert alice["measured"] == alice["allin_n"] == 1
    assert alice["allin_unmeasured_n"] == bob["allin_unmeasured_n"] == 0
    assert alice["luck"] + bob["luck"] == 0

    # expected by hand: 60 in the pot when the flop came, 1000 once all in
    aa, aj = cards_int(["Ah", "Ad"]), cards_int(["Ac", "Jc"])
    flop = [card_int(c) for c in ("Kh", "Qd", "2c")]

    def e(board):
        return equities([aa, aj], board)[0]

    expected = (e(flop) - e([])) * 60
    for turn, river in (("3d", "Ts"), ("4d", "5s")):  # one run lost, one won
        t_, r_ = [card_int(turn)], [card_int(river)]
        expected += (e(flop + t_) - e(flop)) * 500 + (e(flop + t_ + r_) - e(flop + t_)) * 500
    assert alice["luck"] == round(expected)
    # one run each way: the pot was chopped, so this is not a big loss
    assert alice["net"] == -10  # hand 1 chopped, hand 2 blind folded
    assert all(v["n"] == 0 for v in alice["big_loss"].values())

    # identical runs score exactly like the single board
    once = compute_insights(parse_text(_session_json(), source_name="once.json"), big_blind=10)
    twice = compute_insights(parse_text(_rit_json("3d", "Ts", 2), source_name="same.json"), big_blind=10)
    a1 = next(v for k, v in once["luck"].items() if k.startswith("Alice"))
    a2 = next(v for k, v in twice["luck"].items() if k.startswith("Alice"))
    assert a2["luck"] == a1["luck"] and a2["allin_luck"] == a1["allin_luck"]
