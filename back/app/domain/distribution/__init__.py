"""Real Douyin/Kuaishou OAuth + upload + publish integration.

`platform_token_encryption_key` and each platform's app credentials
(`Settings`) default to empty strings — that is the normal "this org has not
finished that platform's business registration yet" state, not a
misconfiguration. Every code path in this package must fail cleanly with a
`PlatformNotConfigured` (503) in that state rather than crash or silently
no-op.
"""

from __future__ import annotations
