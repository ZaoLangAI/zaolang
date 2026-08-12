"""Fixed sampling parameters per LLM model.

An operator picking a model for a judgment `AgentProfile` no longer types a
`max_tokens`/`temperature` number — those two are a property of *the model*,
not of the agent using it, so they are fixed here once and applied
automatically whenever `AgentProfile.model` is set. This lives next to
`app.llm.capabilities` (which learns what a model rejects) rather than in
`app.models` (SQLAlchemy table definitions): both files describe "how this
model behaves", one hand-maintained, one learned from errors.

A model missing from this table falls back to the role's own default (see
`app.agents.base.DEFAULT_ROLE_BINDINGS` and `effective_binding`) exactly like
an agent with nothing configured did before this table existed — this is a
lookup table, not a second source of truth to keep in sync.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelSamplingDefaults:
    max_tokens: int
    temperature: float


# Kept in sync with the models `app.agents.base.DEFAULT_ROLE_BINDINGS`
# already ships defaults for; add an entry here whenever a new model is wired
# into an endpoint so `/admin/agents` can offer it with a fixed binding
# instead of leaving max_tokens/temperature empty.
MODEL_SAMPLING_DEFAULTS: dict[str, ModelSamplingDefaults] = {
    "doubao-seed-2-1-pro": ModelSamplingDefaults(max_tokens=1024, temperature=0.0),
    "kimi-k3": ModelSamplingDefaults(max_tokens=2048, temperature=0.3),
    "ling-3.0-flash-free": ModelSamplingDefaults(max_tokens=4096, temperature=0.7),
}


def for_model(model: str | None) -> ModelSamplingDefaults | None:
    """The fixed sampling parameters for one model, or `None` if unregistered.

    `None` is a legitimate result, not a caller error: it means "keep
    inheriting the role default", which is exactly what an empty
    `max_tokens`/`temperature_milli` already does in `effective_binding`.
    """
    if not model:
        return None
    return MODEL_SAMPLING_DEFAULTS.get(model)
