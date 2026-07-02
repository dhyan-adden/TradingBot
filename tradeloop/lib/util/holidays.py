from datetime import date


NSE_HOLIDAYS_2026: set[date] = set()


def is_nse_holiday(day: date) -> bool:
    return day in NSE_HOLIDAYS_2026

