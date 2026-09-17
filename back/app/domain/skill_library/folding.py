"""Folding a template's `params_json` into a generation request.

Extracted from `app.workflows.nodes` so the workflow pipeline and the canvas'
workflow runs share one implementation. Two callers folding "the same way" by
hand is how a prompt ends up duplicated on one path and missing on the other.

`params_json` is an unvalidated JSON bag on `CreationSkill` — deliberately, so
a new recipe key does not need a migration. That is exactly why folding needs
its own rules: some keys are the recipe, some are the *card's* own metadata,
and only the first group may reach a provider.
"""

from __future__ import annotations

from typing import Any

# Keys a template may contribute to a job's params. A closed list, and only
# applied to image-asset categories: a user-authored template's `params_json`
# can legitimately carry `seed`, `duration_seconds` and the like, so widening
# this whitelist to every skill would silently change what those already do.
TEMPLATE_FOLD_KEYS = frozenset({"prompt", "prompt_suffix", "aspect_ratio", "negative_prompt"})

# Keys that describe the *skill* rather than the generation, and must never be
# folded into `ctx.params` no matter which category the skill is. `variables`
# is a workflow's question list (`app.agents.questions`' field model): it is
# answered before a run is built and the answers are substituted into the
# prompt, so passing the questions themselves to a provider would be sending
# it a form to look at.
RESERVED_TEMPLATE_KEYS = frozenset({"variables"})


def foldable_params(params_json: dict[str, Any] | None) -> dict[str, Any]:
    """Everything a non-image-asset template may fold: the whole bag minus the
    reserved keys."""
    if not params_json:
        return {}
    return {key: value for key, value in params_json.items() if key not in RESERVED_TEMPLATE_KEYS}


def flat_template_params(params_json: dict[str, Any] | None) -> dict[str, Any]:
    """The keys an image-asset skill may fold — never a nested
    `character`/`scene` bundle, whose `reference_assets` would otherwise leak
    into the provider request."""
    if not params_json:
        return {}
    return {key: params_json[key] for key in TEMPLATE_FOLD_KEYS if key in params_json}


def fold_params_prompt(prompt: str, params_json: dict[str, Any]) -> str:
    """Applies a template's prompt the same way the studio's local
    `applyParams` does (`front/src/components/studio/generation-studio.tsx`):
    `prompt` is the template's full directive text, `prompt_suffix` is a
    fragment meant to be tacked on. Appending only when the text is not
    already present keeps the normal path (client already merged it via
    `/apply`, possibly user-edited) from getting it duplicated, while a bare
    API call that never merged locally still ends up with it in the final
    prompt sent to the provider.

    Shared by creation skills and system style-gallery entries — both store
    the same `params_json` shape.
    """
    for key in ("prompt", "prompt_suffix"):
        value = params_json.get(key)
        if isinstance(value, str) and value.strip() and value not in prompt:
            return f"{prompt}，{value}" if prompt else value
    return prompt


__all__ = [
    "RESERVED_TEMPLATE_KEYS",
    "TEMPLATE_FOLD_KEYS",
    "flat_template_params",
    "fold_params_prompt",
    "foldable_params",
]
