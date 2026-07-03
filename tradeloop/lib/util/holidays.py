from datetime import date


# NSE trading holidays 2026 — full-day equity-segment closures per NSE circular
# CMTR71775 (verified 2026-07-03 against two independent sources). Weekday
# closures only; weekends are gated by is_nse_holiday itself. Muhurat trading
# (Sun 2026-11-08) is NOT listed — it is a special session on a non-trading day.
NSE_HOLIDAYS_2026: set[date] = {
    date(2026, 1, 15),   # Maharashtra municipal elections
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi
    date(2026, 3, 26),   # Shri Ram Navami
    date(2026, 3, 31),   # Shri Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 28),   # Bakri Id
    date(2026, 6, 26),   # Muharram
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 10),  # Diwali Balipratipada
    date(2026, 11, 24),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
}
# ponytail: hardcoded 2026 set; swap for an exchange-calendar lib when a second
# year is needed (the is_nse_holiday signature stays the same).


def is_nse_holiday(day: date) -> bool:
    """True when the NSE equity segment is closed: weekends or a listed holiday."""
    return day.weekday() >= 5 or day in NSE_HOLIDAYS_2026
