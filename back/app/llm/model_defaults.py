"""Generic sampling fallback when neither the profile nor the model declares one.

Model ids and token ceilings come from `llm_providers` endpoints
(`max_output_tokens` / `context_length`) and optional `AgentProfile`
overrides. These two numbers only keep a call well-formed when both the
profile and the bound endpoint left those fields empty (0 / NULL).
"""

from __future__ import annotations

DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.2
