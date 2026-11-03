"""UFC module tests - synthetic fixtures only, zero network, zero credits."""
import io
import json

import pytest

from src.ufc import espn, odds as uodds
from src.ufc.common import names_match, no_vig_two_way, prob_to_american, wilson
from src.ufc.grade import grade_card, summarize
from src.ufc.ratings import Ratings, backtest
from src.ufc.status import apply_overrides, diff_status, is_void


def comp(cid, a, b, winner=None, date="2026-10-31T21:00Z", completed=False, period=0,
         clock=0.0, rounds=3, wc="Lightweight", status="STATUS_SCHEDULED"):
    return {"id": cid, "date": date, "type": {"abbreviation": wc},
            "format": {"regulation": {"periods": rounds}},
            "status": {"period": period, "clock": clock,
                       "type": {"name": status if not completed else "STATUS_FINAL", "completed": completed}},
            "competitors": [
                {"id": a[0], "order": 1, "winner": winner == a[0], "athlete": {"displayName": a[1]}},
                {"id": b[0], "order": 2, "winner": winner == b[0], "athlete": {"displayName": b[1]}}]}


def board(*comps, eid="E1", name="UFC Test"):
    return {"events": [{"id": eid, "name": name, "date": comps[0]["date"], "competitions": list(comps)}]}


A, B, C = ("1", "Renato Moicaño"), ("2", "Tom Nolan"), ("3", "Late Sub")


def test_parse_finish_decision_draw():
    fights = espn.parse_scoreboard(board(
        comp("f1", A, B, winner="1", completed=True, period=2, clock=150.0),
        comp("f2", A, B, winner="2", completed=True, period=3, clock=300.0),
        comp("f3", A, B, completed=True, period=3, clock=300.0)))
    assert fights[0]["went_distance"] is False and fights[0]["end_time_rounds"] == 1.5
    assert fights[1]["went_distance"] is True and fights[1]["result"] == "win"
    assert fights[2]["result"] == "draw_or_nc"


def test_name_matching_accents_and_initials():
    assert names_match("Renato Moicaño", "Renato Moicano")
    assert names_match("Tom Nolan", "T. Nolan")  # first initial + last name
    assert not names_match("Tom Nolan", "Tim Smith")


def test_novig_and_american():
    pa, pb = no_vig_two_way(-150, 130)
    assert abs(pa + pb - 1) < 1e-9 and pa > 0.5
    assert prob_to_american(0.6) == -150 and prob_to_american(0.4) == 150
    assert wilson(0, 0) is None
    lo, hi = wilson(5, 10)
    assert lo < 0.5 < hi


ODDS_EVENTS = [
    {"id": "o1", "home_team": "Renato Moicano", "away_team": "Tom Nolan", "bookmakers": [
        {"key": "draftkings", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Tom Nolan", "price": -200}, {"name": "Renato Moicano", "price": 170}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": -120, "point": 2.5},
                                            {"name": "Under", "price": 100, "point": 2.5}]}]},
        {"key": "fanduel", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Tom Nolan", "price": -180}, {"name": "Renato Moicano", "price": 155}]}]}]},
    {"id": "pfl", "home_team": "Some PFL Guy", "away_team": "Other PFL Guy", "bookmakers": []},
]


def test_ufc_filter_and_summary_orientation():
    fight = espn.parse_scoreboard(board(comp("f1", A, B)))[0]
    ev = uodds.match_event(fight, ODDS_EVENTS)
    assert ev["id"] == "o1"
    s = uodds.summarize_event(fight, ev)
    assert s["h2h_novig"][0] < 0.5 < s["h2h_novig"][1]  # Moicano is card fighter 0, underdog
    assert s["best"][0] == {"price": 170, "book": "draftkings"}
    assert s["totals"][0]["line"] == 2.5 and len(s["books"]) == 2
    assert uodds.match_event(espn.parse_scoreboard(board(comp("x", ("9", "Nobody"), ("8", "Else"))))[0],
                             ODDS_EVENTS) is None


class FakeResp(io.BytesIO):
    def __init__(self, body, headers):
        super().__init__(json.dumps(body).encode())
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_budget_guard_and_meter():
    with pytest.raises(uodds.BudgetExceeded):
        uodds.fetch_odds("k", "a", "b", max_credits=1, opener=lambda *a, **k: None)
    body, meter = uodds.fetch_odds("k", "a", "b", opener=lambda *a, **k: FakeResp(
        ODDS_EVENTS, {"x-requests-last": "2", "x-requests-remaining": "498"}))
    assert meter["cost_measured"] == 2 and len(body) == 2
    with pytest.raises(uodds.MeterMissing):
        uodds.fetch_odds("k", "a", "b", opener=lambda *a, **k: FakeResp([], {}))


def history():
    out = []
    for i in range(40):
        out.append(comp(f"h{i}", A, B, winner="1", completed=True, period=1 + i % 3,
                        clock=300.0 if i % 3 == 2 else 120.0, date=f"2024-{1 + i % 12:02d}-{1 + i % 27:02d}T20:00Z"))
    return espn.parse_scoreboard(board(*out))


def test_ratings_and_totals():
    h = history()
    r = Ratings().fit(h)
    assert r.rating("1") > 1500 > r.rating("2")
    fight = espn.parse_scoreboard(board(comp("n", A, B)))[0]
    wp = r.win_prob(fight, {"1": {"age": 40, "reach_in": 70}, "2": {"age": 25, "reach_in": 74}})
    assert abs(sum(wp["p"]) - 1) < 1e-3 and wp["adjustments"][0]["age"] == -96.0
    assert wp["adjustments"][0]["reach"] == -16.0
    overs = [r.p_over(fight, l) for l in (0.5, 1.5, 2.5)]
    assert overs[0] >= overs[1] >= overs[2] and all(0 <= p <= 1 for p in overs)
    bt = backtest(h, warmup=10)
    assert bt["n"] == 30 and "not closing-line" in bt["type"]


def test_status_scratch_replacement_overrides():
    prev = espn.parse_scoreboard(board(comp("f1", A, B)))
    new = espn.parse_scoreboard(board(comp("f2", A, C)))
    st = diff_status(prev, new, {})
    assert st["f1"]["status"] == "scratched" and st["f2"]["status"] == "replacement"
    assert st["f2"]["short_notice"] and is_void(st, "f1") and not is_void(st, "f2")
    st2 = diff_status(prev, [], {})
    assert st2["f1"]["status"] == "cancelled"
    st3 = apply_overrides(st, {"f2": {"status": "missed_weight", "detail": "Late Sub +2.5 lb"}})
    assert st3["f2"]["status"] == "missed_weight" and not is_void(st3, "f2")


def test_grading_void_rules_and_clv():
    card = {"event_id": "E1", "fights": [
        {"fight_id": "f1", "fighters": [{"name": "A"}, {"name": "B"}], "model": {"p": [0.6, 0.4]}},
        {"fight_id": "f2", "fighters": [{"name": "C"}, {"name": "D"}], "model": {"p": [0.6, 0.4]}},
        {"fight_id": "f3", "fighters": [{"name": "E"}, {"name": "F"}], "model": {"p": [0.6, 0.4]}}]}
    snaps = {fid: {"pre": {"h2h_novig": [0.5, 0.5]}, "lock": {"h2h_novig": [0.55, 0.45]}} for fid in ("f1", "f2", "f3")}
    res = {"f1": {"result": "win", "fighters": [{"winner": True}, {"winner": False}]},
           "f2": {"result": "draw_or_nc", "fighters": [{"winner": False}, {"winner": False}]}}
    g = grade_card(card, snaps, res, {"f3": {"status": "cancelled"}})
    by = {r["fight_id"]: r for r in g["decisions"]}
    assert by["f1"]["result"] == "win" and by["f1"]["clv"] == 0.05
    assert by["f2"]["result"] == "void" and by["f3"]["result"] == "void"
    s = summarize([g])
    assert s["n_settled"] == 1 and s["n_void"] == 2 and s["n_clv"] == 1 and s["edge_claim"] == "NO EDGE"
    no_lock = grade_card(card, {"f1": {"pre": {"h2h_novig": [0.5, 0.5]}}}, res, {})
    assert no_lock["decisions"][0]["clv"] is None


def test_next_card_picks_earliest_upcoming():
    from datetime import datetime, timezone
    fs = espn.parse_scoreboard(board(comp("a", A, B, date="2026-11-07T21:00Z"), eid="E2")) + \
        espn.parse_scoreboard(board(comp("b", A, B, date="2026-10-31T21:00Z"), eid="E1"))
    card = espn.next_card(fs, datetime(2026, 10, 31, 8, tzinfo=timezone.utc))
    assert [f["fight_id"] for f in card] == ["b"]
