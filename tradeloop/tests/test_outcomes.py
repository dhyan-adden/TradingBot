from tradeloop.lib.audit.outcomes import Outcome, classify_outcome


def test_target_hit_positive_r_is_thesis_correct_won():
    assert classify_outcome(realized_r=1.8, hit_target=True, hit_stop=False) == Outcome.THESIS_CORRECT_WON


def test_stopped_out_is_thesis_correct_but_stopped_when_thesis_had_edge():
    # stopped at a loss but the plan was coherent (target existed, no thesis break)
    assert classify_outcome(realized_r=-1.0, hit_target=False, hit_stop=True) == Outcome.THESIS_CORRECT_STOPPED


def test_won_without_target_is_thesis_wrong_but_won():
    # exited profitably but not via the planned target -> lucky, thesis path not followed
    assert classify_outcome(realized_r=0.4, hit_target=False, hit_stop=False) == Outcome.THESIS_WRONG_WON


def test_loss_without_stop_is_thesis_wrong_and_lost():
    assert classify_outcome(realized_r=-0.6, hit_target=False, hit_stop=False) == Outcome.THESIS_WRONG_LOST


def test_enum_values_match_prompt_labels():
    assert Outcome.THESIS_CORRECT_WON.value == "thesis-correct-and-won"
    assert Outcome.THESIS_WRONG_LOST.value == "thesis-wrong-and-lost"
