from pathlib import Path

from tradeloop.lib.llm import routing

DOC = Path("tradeloop/prompts/shared/model_routing.md")


def test_doc_has_no_fake_model_ids():
    text = DOC.read_text()
    for fake in ("minimax/minimax-m3", "deepseek/deepseek-v4-flash",
                 "xiaomi/mimo-v2.5", "tencent/hy3-preview"):
        assert fake not in text, f"placeholder model {fake} still in doc"


def test_doc_lists_every_real_stage_model():
    text = DOC.read_text()
    for model in set(routing.STAGE_MODELS.values()):
        assert model in text, f"{model} missing from routing doc"
