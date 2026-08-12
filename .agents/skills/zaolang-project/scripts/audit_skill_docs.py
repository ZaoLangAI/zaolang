#!/usr/bin/env python3
"""Check repository skill references against the current checkout.

This is intentionally static: it catches stale paths, removed component names,
and a few high-signal count claims without importing the application or touching
the database.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = REPO_ROOT / ".cursor" / "skills"
CODE_SPAN = re.compile(r"`([^`\n]+)`")
FILE_NAME = re.compile(
    r"^[A-Za-z0-9_.+\-]+\.(?:css|json|md|mjs|py|sh|swift|ts|tsx|yaml|yml)$"
)
PATH_PREFIXES = (".github/", "assets-pack/", "back/", "docs/", "front/", "infra/", "ios/")
INTENTIONALLY_LOCAL_PATHS = {
    # Created from manifest.example.json only when real media is supplied.
    "assets-pack/manifest.json",
}
IGNORED_DIRS = {
    ".git",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "coverage",
    "node_modules",
}


def repository_files() -> tuple[set[str], set[str]]:
    relative: set[str] = set()
    basenames: set[str] = set()
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or any(part in IGNORED_DIRS for part in path.parts):
            continue
        relative.add(path.relative_to(REPO_ROOT).as_posix())
        basenames.add(path.name)
    return relative, basenames


def clean_path(token: str) -> str | None:
    token = token.strip().rstrip(".,;:，。；）)")
    if not token.startswith(PATH_PREFIXES):
        return None
    if any(marker in token for marker in ("*", "{", "}", "...", " ", "→")):
        return None
    # A table cell may describe an endpoint after a source path.
    path = token.split(":", 1)[0]
    return None if path in INTENTIONALLY_LOCAL_PATHS else path


def queue_names() -> tuple[str, ...]:
    source = REPO_ROOT / "back/app/workers/celery_app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "QUEUE_NAMES" for target in node.targets):
                value = ast.literal_eval(node.value)
                return tuple(value)
    raise RuntimeError("QUEUE_NAMES not found in celery_app.py")


def main() -> int:
    relative_files, basenames = repository_files()
    errors: list[str] = []
    skill_files = sorted(SKILL_ROOT.glob("*/SKILL.md"))
    if not skill_files:
        errors.append("no .cursor skill documents found")

    names: set[str] = set()
    for skill_file in skill_files:
        text = skill_file.read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)
        if len(frontmatter) < 3:
            errors.append(f"{skill_file.relative_to(REPO_ROOT)}: missing YAML frontmatter")
            continue
        match = re.search(r"^name:\s*([^\n]+)$", frontmatter[1], re.MULTILINE)
        if not match:
            errors.append(f"{skill_file.relative_to(REPO_ROOT)}: missing name")
        elif match.group(1).strip() in names:
            errors.append(f"duplicate skill name: {match.group(1).strip()}")
        else:
            names.add(match.group(1).strip())

        for token in CODE_SPAN.findall(text):
            path = clean_path(token)
            if path and path not in relative_files and not (REPO_ROOT / path).is_dir():
                errors.append(f"{skill_file.relative_to(REPO_ROOT)}: missing path `{path}`")

            # Split prose lists such as `tokens.py` / `passwords.py`, but do
            # not split real paths or valid names such as `Color+ZL.swift`.
            for part in re.split(r"\s+/\s+", token):
                candidate = part.strip().rstrip(".,;:，。；）)")
                if FILE_NAME.fullmatch(candidate) and candidate not in basenames:
                    errors.append(
                        f"{skill_file.relative_to(REPO_ROOT)}: missing file name `{candidate}`"
                    )

    jobs_doc = (SKILL_ROOT / "zaolang-generation-jobs/SKILL.md").read_text(encoding="utf-8")
    queues = queue_names()
    if f"{len(queues)} 个队列" not in jobs_doc and f"{len(queues)}个队列" not in jobs_doc:
        errors.append(
            "zaolang-generation-jobs: queue count claim does not match "
            f"QUEUE_NAMES ({len(queues)}: {', '.join(queues)})"
        )

    frontend_doc = (SKILL_ROOT / "zaolang-frontend-ui/SKILL.md").read_text(encoding="utf-8")
    if "12 个页面" in frontend_doc:
        errors.append("zaolang-frontend-ui: stale 12-page claim remains")

    data_doc = (SKILL_ROOT / "zaolang-data-model/SKILL.md").read_text(encoding="utf-8")
    if "单条基线迁移" in data_doc or "六个模型模块" in data_doc:
        errors.append("zaolang-data-model: stale model/migration count claim remains")

    if errors:
        print("Skill documentation audit failed:")
        for error in sorted(set(errors)):
            print(f"- {error}")
        return 1

    page_count = len(list((REPO_ROOT / "front/src/app/[locale]/(site)").rglob("page.tsx")))
    migration_count = len(list((REPO_ROOT / "back/alembic/versions").glob("*.py")))
    print(
        f"OK: {len(skill_files)} module skills; {len(relative_files)} repository files; "
        f"{len(queues)} queues; {page_count} site pages; {migration_count} migrations."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
