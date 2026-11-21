from stock_ai.data.jpx_etf_quotes import compare_monthly_quote


def test_compare_monthly_quote_uses_original_units_across_split():
    bars = [
        {"date": "2024-08-07", "close": "254.00", "volume": "100"},
        {"date": "2024-08-08", "close": "252.30", "volume": "80"},
    ]
    result = compare_monthly_quote(bars, close_mean=(2540 + 252.3) / 2,
                                   volume_mean=(10 + 80) / 2)
    assert result["close_sum_difference_original_units"] == 0
    assert result["volume_difference_original_units"] == 0


def test_compare_monthly_quote_detects_hidden_interior_close_and_volume():
    bars = [
        {"date": "2024-01-04", "close": "246.0", "volume": "100"},
        {"date": "2024-01-15", "close": "259.1", "volume": "200"},
        {"date": "2024-01-31", "close": "264.2", "volume": "300"},
    ]
    result = compare_monthly_quote(bars, close_mean=(2460 + 2613 + 2642) / 3,
                                   volume_mean=(10 + 40 + 30) / 3)
    assert result["close_sum_difference_original_units"] == -22
    assert result["volume_difference_original_units"] == -20
