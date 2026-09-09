from app.domain.publishing.service import DRAFT_TITLE_MAX, title_from_prompt


def test_title_from_prompt_takes_first_line() -> None:
    assert title_from_prompt("雨夜巷口摊牌\n第二行") == "雨夜巷口摊牌"


def test_title_from_prompt_rejects_blank() -> None:
    assert title_from_prompt("   \n  ") is None
    assert title_from_prompt(None) is None
    assert title_from_prompt(12) is None


def test_title_from_prompt_caps_length() -> None:
    assert title_from_prompt("画" * (DRAFT_TITLE_MAX + 8)) == "画" * DRAFT_TITLE_MAX
