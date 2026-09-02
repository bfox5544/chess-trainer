import chess

from chess_trainer.db.enums import Classification as C
from chess_trainer.db.enums import Phase
from chess_trainer.reports import motifs
from chess_trainer.reports.stats import summarize
from chess_trainer.reports.weakness import (
    MoveFact,
    aggregate,
    by_phase,
    opening_key,
    time_pressure_key,
)


def fact(
    classification: C = C.GOOD,
    loss: float = 0.0,
    phase: Phase = Phase.MIDDLEGAME,
    opening: str | None = "Sicilian Defense",
    pressure: bool | None = False,
) -> MoveFact:
    return MoveFact(classification, loss, phase, opening, pressure)


def test_summarize_counts_and_rates() -> None:
    stats = summarize(
        [(C.GOOD, 0.0), (C.GOOD, 1.0), (C.INACCURACY, 6.0), (C.MISTAKE, 12.0), (C.BLUNDER, 31.0)]
    )
    assert (stats.moves, stats.inaccuracies, stats.mistakes, stats.blunders) == (5, 1, 1, 1)
    assert stats.average_win_pct_loss == 10.0
    assert stats.errors_per_100_moves == 40.0  # inaccuracies are not counted as errors


def test_summarize_of_nothing_is_all_zero() -> None:
    stats = summarize([])
    assert (stats.moves, stats.average_win_pct_loss, stats.errors_per_100_moves) == (0, 0.0, 0.0)


def test_phases_are_reported_in_game_order() -> None:
    facts = [
        fact(phase=Phase.ENDGAME, classification=C.BLUNDER, loss=40),
        fact(phase=Phase.ENDGAME),
        fact(phase=Phase.ENDGAME),
        fact(phase=Phase.OPENING),
        fact(phase=Phase.MIDDLEGAME, classification=C.MISTAKE, loss=11),
    ]
    buckets = by_phase(facts)
    assert [b.key for b in buckets] == ["opening", "middlegame", "endgame"]
    assert buckets[2].stats.blunders == 1 and buckets[2].stats.moves == 3
    assert buckets[1].stats.errors_per_100_moves == 100.0


def test_openings_are_ranked_by_sample_size_with_unknown_named() -> None:
    facts = [fact(opening="Italian Game")] * 3 + [fact(opening="Sicilian Defense")] * 5
    facts.append(fact(opening=None, classification=C.BLUNDER, loss=20))
    buckets = aggregate(facts, opening_key)
    assert [(b.key, b.stats.moves) for b in buckets] == [
        ("Sicilian Defense", 5),
        ("Italian Game", 3),
        ("Unknown", 1),
    ]


def test_moves_without_clock_data_are_left_out_of_time_pressure() -> None:
    facts = [
        fact(pressure=True, classification=C.BLUNDER, loss=30),
        fact(pressure=True),
        fact(pressure=False),
        fact(pressure=False),
        fact(pressure=False),
        fact(pressure=None, classification=C.BLUNDER, loss=30),
    ]
    buckets = {b.key: b.stats for b in aggregate(facts, time_pressure_key)}
    assert set(buckets) == {"under_pressure", "not_under_pressure"}
    assert buckets["under_pressure"].errors_per_100_moves == 50.0
    assert buckets["not_under_pressure"].blunders == 0


def test_motif_extension_point_is_wired_but_empty() -> None:
    assert motifs.REGISTRY == []
    assert motifs.tag_motifs(chess.Board(), chess.Move.from_uci("e2e4"), []) == []


def test_registered_taggers_are_combined(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Always:
        def __init__(self, name: str) -> None:
            self.name = name

        def tags(self, board: object, played: object, best_line: object) -> set[str]:
            return {self.name}

    monkeypatch.setattr(motifs, "REGISTRY", [Always("pin"), Always("fork")])
    assert motifs.tag_motifs(chess.Board(), chess.Move.from_uci("e2e4"), []) == ["fork", "pin"]
