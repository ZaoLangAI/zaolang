"""The configurable generation workflow engine.

- `registry` — whitelist of code-reviewed node types an admin can wire up.
- `graph` — the graph data structure and its publish-time structural validator.
- `configs` — per-node-type Pydantic config schemas.
- `nodes` — the node executors (the only code that may touch credits/state).
- `runner` — `WorkflowRunner`, which walks a graph and calls those executors.
- `defaults` — the code-level fallback graph shape, seeded per `Operation`.
- `shape` — `describe_workflow`, the ops console's declared-timeline view.
"""

from __future__ import annotations

from app.workflows.shape import describe_workflow

__all__ = ["describe_workflow"]
