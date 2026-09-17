"""`.cursor/skills` must keep pointing at code that exists.

The skills are hand-maintained maps of the codebase and drift silently: a
renamed module, a new upload purpose or a new worker queue leaves every later
reader — human or agent — working from a wrong map. These checks are strict
only on facts a machine can verify (referenced paths and symbols, `make`
targets, queue lists, the storage whitelists) and leave the prose alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.storage import s3
from app.workers.celery_app import QUEUE_NAMES

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".cursor" / "skills"
SKILL_FILES = sorted(SKILLS_DIR.glob("*/*.md"))

_PATH_REF = re.compile(r"`((?:back|front|infra)/[^`\s]+)`")
_MAKE_REF = re.compile(r"`make ([a-z][a-z0-9-]*)")
# `path:12` / `path:12-40` are line hints; `path:symbol` and `path::symbol`
# (a pytest node id) name something that must still be defined in that file.
_LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")
_SYMBOL_SUFFIX = re.compile(r"::?([A-Za-z_][A-Za-z0-9_]*)$")
# Created on the server / by the developer, never committed.
_RUNTIME_FILE = re.compile(r"^\.env(?:\.(?!example$).+)?$")

_NUMBER_WORDS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


def _skill_name(path: Path) -> str:
    return path.relative_to(SKILLS_DIR).as_posix()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_skills_are_present() -> None:
    assert len(SKILL_FILES) >= 20, f"expected the module skills under {SKILLS_DIR}"


def test_every_referenced_path_and_symbol_exists() -> None:
    stale: list[str] = []
    for skill in SKILL_FILES:
        for ref in sorted(set(_PATH_REF.findall(_text(skill)))):
            raw = _LINE_SUFFIX.sub("", ref)
            symbol = None
            match = _SYMBOL_SUFFIX.search(raw)
            if match:
                symbol, raw = match.group(1), raw[: match.start()]
            if any(ch in raw for ch in "*{}<>"):
                continue  # a pattern, not a single path
            if _RUNTIME_FILE.match(Path(raw).name):
                continue
            target = REPO_ROOT / raw.rstrip("/")
            if not target.exists():
                stale.append(f"{_skill_name(skill)}: `{ref}` — path not found")
            elif symbol and target.is_file():
                source = target.read_text(encoding="utf-8", errors="ignore")
                if not re.search(rf"\b{re.escape(symbol)}\b", source):
                    stale.append(f"{_skill_name(skill)}: `{ref}` — symbol not found")
    assert not stale, "stale skill references:\n" + "\n".join(stale)


def test_every_referenced_make_target_exists() -> None:
    makefile = _text(REPO_ROOT / "Makefile")
    targets = set(re.findall(r"^([A-Za-z0-9][A-Za-z0-9_-]*):", makefile, re.MULTILINE))
    unknown = sorted(
        f"{_skill_name(skill)}: make {target}"
        for skill in SKILL_FILES
        for target in set(_MAKE_REF.findall(_text(skill)))
        if target not in targets
    )
    assert not unknown, "skills mention make targets that do not exist:\n" + "\n".join(unknown)


def _worker_queue_groups(text: str) -> list[set[str]]:
    # Makefile: `-Q a,b,c`; compose: a `- -Q` list item followed by `- a,b,c`.
    inline = re.findall(r"-Q\s+([a-z_,]+)", text)
    compose = re.findall(r"-\s+-Q\s*\n\s*-\s+([a-z_,]+)", text)
    return [set(group.split(",")) for group in inline + compose]


@pytest.mark.parametrize(
    "relative_path",
    ["Makefile", "infra/docker-compose.prod.yml", "infra/docker-compose.release.yml"],
)
def test_worker_queue_lists_cover_exactly_queue_names(relative_path: str) -> None:
    groups = _worker_queue_groups(_text(REPO_ROOT / relative_path))
    assert groups, f"no `-Q` worker queue list found in {relative_path}"
    consumed = set().union(*groups)
    assert consumed == set(QUEUE_NAMES), (
        f"{relative_path} consumes {sorted(consumed)}, QUEUE_NAMES is {sorted(QUEUE_NAMES)}"
    )


def test_every_queue_is_named_in_some_skill() -> None:
    corpus = "\n".join(_text(skill) for skill in SKILL_FILES)
    undocumented = [queue for queue in QUEUE_NAMES if f"`{queue}`" not in corpus]
    assert not undocumented, f"queues no skill mentions: {undocumented}"


def test_media_assets_skill_matches_the_storage_whitelists() -> None:
    text = _text(SKILLS_DIR / "zaolang-media-assets" / "SKILL.md")
    assert set(s3.PURPOSE_PREFIXES) == set(s3.MAX_UPLOAD_BYTES)

    missing = [f"purpose `{name}`" for name in s3.PURPOSE_PREFIXES if f"`{name}`" not in text]
    missing += [
        f"MIME `{mime}`" for mime in s3.ALLOWED_UPLOAD_MIME_TYPES if f"`{mime}`" not in text
    ]
    assert not missing, "zaolang-media-assets skill is missing: " + ", ".join(missing)

    stated = re.search(r"\((\w+) purposes", text)
    assert stated, "media-assets skill no longer states how many upload purposes exist"
    assert _NUMBER_WORDS.get(stated.group(1)) == len(s3.PURPOSE_PREFIXES), (
        f"skill says {stated.group(1)} purposes, code has {len(s3.PURPOSE_PREFIXES)}"
    )
