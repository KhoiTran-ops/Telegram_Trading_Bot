from signal_engine.engine import Bar
from reporting.market_summary import build_market_summary


def test_market_summary_calculates_index_move_and_highlights() -> None:
    index = [
        Bar(1, 1000, 1005, 995, 1000, 1),
        Bar(2, 1000, 1015, 998, 1010, 1),
    ]
    movers = [("AAA", 5.2, 10_000_000_000), ("BBB", -3.1, 20_000_000_000)]

    summary = build_market_summary(index, movers, session="MORNING")

    assert summary.points_change == 10
    assert summary.percent_change == 1
    assert summary.advancers == 1
    assert summary.decliners == 1
    assert summary.highlights[0].symbol == "AAA"
