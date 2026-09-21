from signal_engine.fundamentals import FinancialQuarter, evaluate_fundamentals


def test_fundamentals_compute_ttm_growth_and_warnings() -> None:
    quarters = [
        FinancialQuarter(2024 + index // 4, index % 4 + 1,
                         revenue=100 + index * 10, profit=20 + index * 5,
                         equity=500 + index * 10, debt=300,
                         current_assets=250, current_liabilities=100,
                         cfo=25 + index * 5)
        for index in range(8)
    ]

    result = evaluate_fundamentals(quarters)

    assert result.mandatory_pass is True
    assert result.grade == "A"
    assert result.metrics["profit_ttm"] == 190
    assert "valuation_pe_pb" not in result.missing


def test_missing_financial_item_is_explicit() -> None:
    quarters = [FinancialQuarter(2025, 1, revenue=None, profit=10,
                                 equity=100, debt=None, current_assets=None,
                                 current_liabilities=None, cfo=None)]

    result = evaluate_fundamentals(quarters)

    assert result.mandatory_pass is None
    assert "eight_quarters" in result.missing
    assert "revenue" in result.missing
