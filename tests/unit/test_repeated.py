from datetime import datetime

from chess_trainer.db.enums import Classification, Color
from chess_trainer.reports.repeated import ErrorRow, group_errors, position_key

FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/3PP3/5N2/PPP2PPP/RNBQKB1R b KQkq - 0 3"
OTHER = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1"


def error(
    game_id: int,
    *,
    fen: str = FEN,
    san: str = "f6",
    uci: str = "f7f6",
    ply: int = 5,
    kind: Classification = Classification.MISTAKE,
    loss: float = 10.0,
    best: str | None = "e5d4",
    family: str | None = "Scotch Game",
    day: int = 1,
) -> ErrorRow:
    return ErrorRow(
        game_id=game_id,
        played_at=datetime(2026, 1, day),
        opening_family=family,
        ply=ply,
        move_number=ply // 2 + 1,
        color=Color.BLACK,
        fen_before=fen,
        uci=uci,
        san=san,
        best_move_uci=best,
        best_move_san="exd4" if best == "e5d4" else best,
        classification=kind,
        win_pct_loss=loss,
    )


def test_position_key_ignores_move_counters() -> None:
    assert position_key(FEN) == position_key(FEN.replace("0 3", "4 9"))


def test_a_position_repeated_across_games_is_grouped() -> None:
    rows = [
        error(1, day=1),
        error(2, day=3, kind=Classification.BLUNDER, loss=30.0, fen=FEN.replace("0 3", "2 5")),
        error(3, day=2, san="Nf6", uci="g8f6", family=None),
        error(4, fen=OTHER, san="e5", uci="e7e5"),
    ]
    (group,) = group_errors(rows)
    assert group.games == 3
    assert [o.game_id for o in group.occurrences] == [2, 3, 1]  # newest first
    assert group.worst is Classification.BLUNDER
    assert group.average_win_pct_loss == round(50 / 3, 1)
    assert [(m.san, m.count) for m in group.played] == [("f6", 2), ("Nf6", 1)]
    assert (group.best_move_san, group.best_move_uci) == ("exd4", "e5d4")
    assert group.families == ["Scotch Game", "Unknown"]


def test_repeats_within_one_game_count_once() -> None:
    rows = [error(1, ply=5), error(1, ply=9)]
    assert group_errors(rows) == []
    (group,) = group_errors(rows, min_games=1)
    assert group.games == 1 and group.occurrences[0].ply == 5


def test_groups_are_ordered_by_games_then_cost() -> None:
    rows = [
        error(1, fen=OTHER, loss=5),
        error(2, fen=OTHER, loss=5),
        error(3, loss=40),
        error(4, loss=40),
        error(5, fen=OTHER, loss=5),
    ]
    assert [g.games for g in group_errors(rows)] == [3, 2]
    cheap = [error(1, fen=OTHER, loss=1), error(2, fen=OTHER, loss=1), error(3), error(4)]
    assert [g.key for g in group_errors(cheap)] == [position_key(FEN), position_key(OTHER)]


def test_most_common_best_move_wins() -> None:
    rows = [error(1, best="g8f6"), error(2), error(3)]
    (group,) = group_errors(rows)
    assert group.best_move_uci == "e5d4"
