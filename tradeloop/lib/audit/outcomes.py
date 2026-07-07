from enum import Enum


class Outcome(str, Enum):
    THESIS_CORRECT_WON = "thesis-correct-and-won"
    THESIS_CORRECT_STOPPED = "thesis-correct-but-stopped"
    THESIS_WRONG_WON = "thesis-wrong-but-won"
    THESIS_WRONG_LOST = "thesis-wrong-and-lost"


def classify_outcome(realized_r: float, hit_target: bool, hit_stop: bool) -> Outcome:
    """Map a closed trade onto the four post-trade categories.

    thesis "followed" == the trade resolved via its planned exits (target or stop).
    - target hit                    -> correct & won
    - stop hit (planned loss)       -> correct but stopped
    - profit without hitting target -> wrong path but won
    - loss without hitting stop     -> wrong & lost
    """
    if hit_target:
        return Outcome.THESIS_CORRECT_WON
    if hit_stop:
        return Outcome.THESIS_CORRECT_STOPPED
    if realized_r > 0:
        return Outcome.THESIS_WRONG_WON
    return Outcome.THESIS_WRONG_LOST
