from pathlib import Path

from tradeloop.lib.llm import routing

DOC = Path("tradeloop/prompts/shared/model_routing.md")


def test_doc_has_no_retired_model_ids():
    text = DOC.read_text()
    for retired in ("anthropic/claude-opus-4.5", "anthropic/claude-sonnet-4.5",
                    "anthropic/claude-haiku-4.5", "deepseek/deepseek-v3.2"):
        assert retired not in text, f"retired model {retired} still in doc"


def test_doc_lists_every_real_stage_model():
    text = DOC.read_text()
    for model in set(routing.STAGE_MODELS.values()):
        assert model in text, f"{model} missing from routing doc"
