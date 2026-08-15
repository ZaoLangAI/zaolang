"""Generic sampling fallback when an AgentProfile does not store its own.

Model ids themselves are never listed here: they come from `llm_providers`
and `AgentProfile.model`. These two numbers only keep a call well-formed
when the profile left max_tokens/temperature empty.
"""

from __future__ import annotations

DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.2
