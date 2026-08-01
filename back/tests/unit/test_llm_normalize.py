"""Response normalisation.

Each case mirrors a shape actually observed from the AIHubMix gateway.
"""

from __future__ import annotations

from app.llm.normalize import extract_json, normalize_completion, strip_thinking


def test_think_block_is_removed() -> None:
    text = '<think>让我想想 JSON 结构</think>\n{"decision": "approve"}'

    assert strip_thinking(text) == '{"decision": "approve"}'


def test_unterminated_think_block_is_removed() -> None:
    """Truncation can cut a response mid-thought, leaving no closing tag."""
    text = '{"a": 1}\n<think>继续推理但被截断'

    assert strip_thinking(text) == '{"a": 1}'


def test_json_is_extracted_from_a_fenced_block() -> None:
    text = 'Here is the result:\n```json\n{"verdict": "pass"}\n```'

    assert extract_json(text) == {"verdict": "pass"}


def test_json_is_extracted_from_surrounding_prose() -> None:
    text = '好的，结论如下：{"decision": "reject", "reason_code": "X"} 以上。'

    assert extract_json(text) == {"decision": "reject", "reason_code": "X"}


def test_braces_inside_strings_do_not_break_extraction() -> None:
    text = '{"note": "包含 } 和 { 的文本", "ok": true}'

    assert extract_json(text) == {"note": "包含 } 和 { 的文本", "ok": True}


def test_non_object_json_is_rejected() -> None:
    assert extract_json("[1, 2, 3]") is None
    assert extract_json("完全没有 JSON") is None


def test_clean_json_response_is_passed_through() -> None:
    raw = {
        "model": "doubao-seed-2-1-pro",
        "choices": [{"message": {"content": '{"decision": "approve"}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 18},
    }

    result = normalize_completion(raw, expect_json=True)

    assert result.data == {"decision": "approve"}
    assert result.prompt_tokens == 120
    assert result.warnings == []


def test_thinking_prefix_is_stripped_before_parsing() -> None:
    raw = {
        "model": "kimi-k3",
        "choices": [
            {
                "message": {"content": '<think>先分析</think>{"verdict": "pass"}'},
                "finish_reason": "stop",
            }
        ],
    }

    result = normalize_completion(raw, expect_json=True)

    assert result.data == {"verdict": "pass"}


def test_reasoning_only_response_is_recovered() -> None:
    """`ling-3.0-flash-free` bills thinking against max_tokens.

    With a small budget the content field is empty and the answer only exists
    in reasoning_details.
    """
    raw = {
        "model": "ling-3.0-flash-free",
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_details": [{"text": '{"title": "深海霓虹"}'}],
                },
                "finish_reason": "length",
            }
        ],
    }

    result = normalize_completion(raw, expect_json=True)

    assert result.recovered_from_reasoning is True
    assert result.data == {"title": "深海霓虹"}
    assert result.truncated is True
    assert "truncated_by_max_tokens" in result.warnings


def test_unparseable_json_is_flagged_rather_than_raising() -> None:
    raw = {
        "model": "kimi-k3",
        "choices": [
            {"message": {"content": "抱歉，我无法给出结构化结果"}, "finish_reason": "stop"}
        ],
    }

    result = normalize_completion(raw, expect_json=True)

    assert result.data is None
    assert "json_parse_failed" in result.warnings
    assert result.text


def test_plain_text_mode_does_not_attempt_json() -> None:
    raw = {"choices": [{"message": {"content": "一段说明文字"}, "finish_reason": "stop"}]}

    result = normalize_completion(raw, expect_json=False)

    assert result.data is None
    assert result.warnings == []


def test_sdk_style_object_is_accepted() -> None:
    class FakeCompletion:
        def model_dump(self) -> dict[str, object]:
            return {
                "model": "kimi-k3",
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }

    result = normalize_completion(FakeCompletion(), expect_json=True)

    assert result.data == {"ok": True}
    assert result.model == "kimi-k3"
