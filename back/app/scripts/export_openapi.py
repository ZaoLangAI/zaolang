"""Writes the OpenAPI document to `back/openapi.json`.

The file is committed so the frontend can generate its types without a running
server, and so a contract change shows up as a reviewable diff rather than as a
runtime surprise. `make openapi-check` fails the gate when the committed copy
drifts from the code.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# AgentOS mounts extra routes that are not part of the product contract, and the
# export must not depend on a reachable database.
os.environ.setdefault("APP_ENV", "test")
os.environ["AGENT_OS_ENABLED"] = "false"
os.environ["LLM_MODE"] = "stub"

OUTPUT = Path(__file__).resolve().parents[2] / "openapi.json"


def main() -> None:
    from app.main import create_app

    document = create_app().openapi()
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(Path.cwd())} ({len(document['paths'])} paths)")


if __name__ == "__main__":
    main()
