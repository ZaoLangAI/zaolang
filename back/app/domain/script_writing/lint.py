"""Deterministic script lint: code checks for the writing rules the script
coach already asks for, run on a saved script without an LLM call.

The copywriter prompts (`app/agents/copywriter.py`: `_BLOCK_TYPE_RULES`,
`_ENHANCE_CONTRACT`, `_BREAKPOINT_RULES`) tell the model how to write each
colour block; nothing checked afterwards whether it did. These checks only
*suggest* — they never block a turn, never rewrite text, and never insert or
remove a breakpoint (that would shift every `{heading}#{ordinal}` key and
orphan the drafts bound to them). Every vocabulary word below also appears in
the prompt text it enforces; `tests/unit/test_script_lint.py` asserts that, so
the lint and the coach cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from app.domain.prompts import PROMPT_ENHANCE_MAX_LENGTH
from app.platform_config.schemas import MAX_GENERATION_DURATION_SECONDS

# Longest first, so 「大远景」 is not read as 「远景」 nor 「中近景」 as 「近景」.
SHOT_SIZES: tuple[str, ...] = ("大远景", "大特写", "中近景", "远景", "全景", "中景", "近景", "特写")
WIDE_SHOTS = frozenset({"大远景", "远景"})
# The coach's own duration baselines (`_BREAKPOINT_RULES`): shot size sets a
# shot's natural length, Chinese dialogue runs three to four characters a
# second, one action beat takes two to four seconds.
_SHOT_BASELINE_SECONDS = {
    "大远景": 10.0,
    "远景": 10.0,
    "全景": 8.0,
    "中景": 6.0,
    "中近景": 5.0,
    "近景": 4.0,
    "特写": 4.0,
    "大特写": 4.0,
}
_UNKNOWN_SHOT_SECONDS = 6.0
DIALOGUE_CHARS_PER_SECOND = 3.5
ACTION_BEAT_SECONDS = 3.0

# Words that carry no picture information (`_ENHANCE_CONTRACT`).
VAGUE_WORDS: tuple[str, ...] = (
    "氛围感拉满",
    "大片质感",
    "电影感",
    "震撼",
    "绝美",
    "高级",
    "精美",
    "8K",
)
# Emotion labels an action block must externalise instead (`_BLOCK_TYPE_RULES`).
EMOTION_LABELS: tuple[str, ...] = ("情绪爆发", "气氛紧张", "悲伤", "紧张")
# A camera move needs a direction (`_BLOCK_TYPE_RULES` bans 「镜头缓缓移动」).
DIRECTIONLESS_MOVE_EXAMPLE = "镜头缓缓移动"
_DIRECTION_WORDS = ("左", "右", "上", "下", "前", "后", "推", "拉", "升", "降", "环绕", "跟")

SAME_SHOT_RUN = 3
MAX_SPEAKING_LEADS = 3
VERTICAL_CHANNELS = frozenset({"douyin", "kuaishou"})

_DIMENSION_BY_BLOCK = {"scene": "subject", "action": "action", "camera": "camera"}


@dataclass(frozen=True, slots=True)
class LintIssue:
    code: str
    severity: str  # "warning" | "info"
    message: str
    scene_index: int | None = None
    heading: str = ""
    block_index: int | None = None
    breakpoint_key: str | None = None
    # A format-skill dimension (subject/camera/action/lighting/pacing), so a
    # caller can suggest the matching `fmt-*` skills.
    dimension: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_vertical_delivery(target_platforms: Iterable[str] | None) -> bool:
    """Short dramas default to vertical: only a series that names delivery
    channels and none of them vertical is treated as landscape."""
    platforms = {str(platform) for platform in target_platforms or []}
    platforms.discard("manual_download")
    return not platforms or bool(platforms & VERTICAL_CHANNELS)


def shot_size(text: str) -> str | None:
    for size in SHOT_SIZES:
        if size in text:
            return size
    return None


def lint_script(script: Mapping[str, Any], *, vertical: bool = True) -> list[LintIssue]:
    """All findings for a saved `ScriptDocument`-shaped dict, in script order."""
    names = [
        name
        for name in (
            str(character.get("name") or "").strip()
            for character in script.get("characters") or []
            if isinstance(character, Mapping)
        )
        # A one-character name matches far too many unrelated words.
        if len(name) >= 2
    ]
    issues: list[LintIssue] = []
    speakers: set[str] = set()
    for scene_index, raw_scene in enumerate(script.get("scenes") or []):
        if not isinstance(raw_scene, Mapping):
            continue
        heading = str(raw_scene.get("heading") or "")
        blocks = [block for block in raw_scene.get("blocks") or [] if isinstance(block, Mapping)]
        issues.extend(_block_issues(scene_index, heading, blocks, names))
        issues.extend(_same_shot_run_issues(scene_index, heading, blocks))
        issues.extend(_segment_issues(scene_index, heading, blocks, vertical=vertical))
        speakers.update(
            str(block.get("character") or "").strip()
            for block in blocks
            if block.get("type") == "dialogue"
        )
    speakers.discard("")
    if len(speakers) > MAX_SPEAKING_LEADS:
        issues.append(
            LintIssue(
                code="too_many_speakers",
                severity="info",
                message=(
                    f"这一集有 {len(speakers)} 个说话角色。竖屏短剧的主要角色建议不超过"
                    f" {MAX_SPEAKING_LEADS} 个，观众才记得住谁是谁。"
                ),
            )
        )
    return issues


def _quoted(words: Sequence[str]) -> str:
    return "「" + "」「".join(words) + "」"


def _block_issues(
    scene_index: int, heading: str, blocks: Sequence[Mapping[str, Any]], names: Sequence[str]
) -> list[LintIssue]:
    issues: list[LintIssue] = []
    for index, block in enumerate(blocks):
        kind = block.get("type")
        text = str(block.get("text") or "")
        where: dict[str, Any] = {
            "scene_index": scene_index,
            "heading": heading,
            "block_index": index,
        }
        if kind in _DIMENSION_BY_BLOCK:
            vague = [word for word in VAGUE_WORDS if word in text]
            if vague:
                issues.append(
                    LintIssue(
                        code="vague_words",
                        severity="info",
                        message=(
                            f"{_quoted(vague)}没有画面信息，换成看得见的锚点：焦段与景深、"
                            "光源方向与色温、表面材质或三到五个具体颜色。"
                        ),
                        dimension=_DIMENSION_BY_BLOCK[str(kind)],
                        **where,
                    )
                )
        if kind == "action":
            labels = [word for word in EMOTION_LABELS if word in text]
            if labels:
                issues.append(
                    LintIssue(
                        code="emotion_label",
                        severity="warning",
                        message=(
                            f"动作色块写了{_quoted(labels)}，模型画不出情绪词。"
                            "改成看得见的生理信号，例如肩膀微颤、手指攥紧衣角。"
                        ),
                        dimension="action",
                        **where,
                    )
                )
        if kind == "scene":
            present = [name for name in names if name in text]
            if present:
                issues.append(
                    LintIssue(
                        code="person_in_scene_block",
                        severity="warning",
                        message=(
                            f"场景色块里出现了角色{_quoted(present)}，会让场景图跑出人物。"
                            "场景色块只写空间本身，人物放进 action 色块。"
                        ),
                        dimension="subject",
                        **where,
                    )
                )
        if kind == "camera":
            if shot_size(text) is None:
                issues.append(
                    LintIssue(
                        code="camera_missing_shot_size",
                        severity="info",
                        message="镜头色块没有写景别：先写大远景/远景/全景/中景/中近景/近景/特写/大特写之一，再写运镜。",
                        dimension="camera",
                        **where,
                    )
                )
            if "移动" in text and not any(word in text for word in _DIRECTION_WORDS):
                issues.append(
                    LintIssue(
                        code="camera_directionless_move",
                        severity="warning",
                        message="运镜没有方向。写清方式＋方向＋速度，例如「中近景，缓慢向左平移」。",
                        dimension="camera",
                        **where,
                    )
                )
    return issues


def _same_shot_run_issues(
    scene_index: int, heading: str, blocks: Sequence[Mapping[str, Any]]
) -> list[LintIssue]:
    issues: list[LintIssue] = []
    previous: str | None = None
    run = 0
    for index, block in enumerate(blocks):
        if block.get("type") != "camera":
            continue
        size = shot_size(str(block.get("text") or ""))
        run = run + 1 if size is not None and size == previous else 1
        previous = size
        if size is not None and run == SAME_SHOT_RUN:
            issues.append(
                LintIssue(
                    code="same_shot_run",
                    severity="warning",
                    message=(
                        f"连续 {SAME_SHOT_RUN} 个镜头都是「{size}」，节奏会发平。"
                        "在其中插一个不同景别（例如特写反应镜头）。"
                    ),
                    scene_index=scene_index,
                    heading=heading,
                    block_index=index,
                    dimension="camera",
                )
            )
    return issues


def _segment_issues(
    scene_index: int,
    heading: str,
    blocks: Sequence[Mapping[str, Any]],
    *,
    vertical: bool,
) -> list[LintIssue]:
    """One pass per generation segment: the blocks between two breakpoints
    (or the scene start/end), keyed the same way the frontend keys them."""
    issues: list[LintIssue] = []
    segment: list[tuple[int, Mapping[str, Any]]] = []
    ordinal = 0

    def close(breakpoint_index: int | None) -> None:
        shootable = [
            (index, block) for index, block in segment if str(block.get("text") or "").strip()
        ]
        if not shootable:
            return
        key = f"{heading}#{ordinal}"
        where: dict[str, Any] = {
            "scene_index": scene_index,
            "heading": heading,
            "block_index": breakpoint_index,
            "breakpoint_key": key,
        }
        seconds = sum(_estimated_seconds(block) for _, block in shootable)
        if seconds > MAX_GENERATION_DURATION_SECONDS:
            issues.append(
                LintIssue(
                    code="segment_too_long",
                    severity="warning",
                    message=(
                        f"这一段估算约 {seconds:.0f} 秒，超过单条生成"
                        f" {MAX_GENERATION_DURATION_SECONDS} 秒上限，"
                        "建议在一个自然节拍处（反转、反应镜头、转场）加切分点。"
                    ),
                    dimension="pacing",
                    **where,
                )
            )
        characters = sum(len(str(block.get("text") or "")) for _, block in shootable)
        if characters > PROMPT_ENHANCE_MAX_LENGTH:
            issues.append(
                LintIssue(
                    code="segment_prompt_too_long",
                    severity="warning",
                    message=(
                        f"这一段拼成的提示词约 {characters} 字，超过 {PROMPT_ENHANCE_MAX_LENGTH}"
                        " 字上限，超出部分会被截断。"
                    ),
                    **where,
                )
            )
        if vertical and any(block.get("type") == "dialogue" for _, block in shootable):
            wide = next(
                (
                    index
                    for index, block in shootable
                    if block.get("type") == "camera"
                    and shot_size(str(block.get("text") or "")) in WIDE_SHOTS
                ),
                None,
            )
            if wide is not None:
                issues.append(
                    LintIssue(
                        code="vertical_wide_shot_with_dialogue",
                        severity="info",
                        message="竖屏里人物在远景中会小到看不清表情，有台词的段落优先用中景到特写。",
                        scene_index=scene_index,
                        heading=heading,
                        block_index=wide,
                        breakpoint_key=key,
                        dimension="camera",
                    )
                )

    for index, block in enumerate(blocks):
        if block.get("type") == "breakpoint":
            close(index)
            segment = []
            ordinal += 1
        else:
            segment.append((index, block))
    close(None)
    return issues


def _estimated_seconds(block: Mapping[str, Any]) -> float:
    kind = block.get("type")
    text = str(block.get("text") or "")
    if kind == "dialogue":
        return len(text.strip()) / DIALOGUE_CHARS_PER_SECOND
    if kind == "camera":
        size = shot_size(text)
        return _SHOT_BASELINE_SECONDS[size] if size else _UNKNOWN_SHOT_SECONDS
    if kind == "action":
        return ACTION_BEAT_SECONDS
    return 0.0
