from openpyxl import Workbook

from stock_ai.data.jpx_monthly import audit_monthly, read_1475_segments


def save_book(path, records):
    wb = Workbook()
    ws = wb.active
    for ym, first, last, prices, total, tostnet, days in records:
        row = [None] * 24
        row[0], row[1] = ym, "1475"
        row[10], row[11] = prices[0], str(first)
        row[12], row[14], row[16], row[17] = prices[1], prices[2], prices[3], str(last)
        row[19], row[20], row[23] = total, tostnet, days
        ws.append(row)
    wb.save(path)


def test_monthly_auction_volume_excludes_tostnet(tmp_path):
    path = tmp_path / "jpx.xlsx"
    save_book(path, [("2026/01", 5, 6, (100, 104, 99, 103), 250, 100, 2)])
    segments = read_1475_segments(path)
    bars = [
        {"date": "2026-01-05", "open": "100", "high": "102", "low": "99", "close": "101", "volume": "70"},
        {"date": "2026-01-06", "open": "101", "high": "104", "low": "100", "close": "103", "volume": "80"},
    ]
    result = audit_monthly(bars, segments)
    assert result["issues"] == []
    assert result["audited_rows"] == 2
    bars[1]["volume"] = "81"
    assert audit_monthly(bars, segments)["issues"][0]["field"] == "volume"


def test_split_before_august_8_normalizes_price_and_volume(tmp_path):
    path = tmp_path / "jpx.xlsx"
    save_book(path, [
        ("2024/08", 7, 7, (2540, 2550, 2530, 2540), 20, 10, 1),
        ("2024/08", 8, 8, (250.8, 257.4, 249.0, 252.3), 120, 20, 1),
    ])
    bars = [
        {"date": "2024-08-07", "open": "254", "high": "255", "low": "253", "close": "254", "volume": "100"},
        {"date": "2024-08-08", "open": "250.8", "high": "257.4", "low": "249", "close": "252.3", "volume": "100"},
    ]
    assert audit_monthly(bars, read_1475_segments(path))["issues"] == []
