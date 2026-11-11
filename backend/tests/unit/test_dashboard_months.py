"""Six-month trend window (BR-11)."""

from datetime import date

from finance_app.modules.dashboard.service import months_back


def test_six_months_ending_with_the_month_oldest_first() -> None:
    assert months_back(date(2026, 11, 17), 6) == [
        date(2026, 6, 1),
        date(2026, 7, 1),
        date(2026, 8, 1),
        date(2026, 9, 1),
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]


def test_window_crosses_the_year_boundary() -> None:
    assert months_back(date(2026, 2, 1), 4) == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]
