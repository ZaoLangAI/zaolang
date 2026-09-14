"""Delivery direction for TTS.

The script marks a dialogue line with one closed `emotion`
(`app.agents.copywriter.SCRIPT_EMOTIONS`), carried to the provider as
`GenerationRequest.extra["emotion"]`. Each upstream takes delivery
differently, so it is mapped here, in one place, rather than per provider:

- `tts-pro` (ByteDance, via DMXAPI) has its own `emotion` field with a
  smaller set — anything outside it is dropped, not sent.
- `gpt-4o-mini-tts` takes free-text `instructions`.
- `tts-1` / `tts-1-hd` take neither; the line is voiced plainly.

An unknown or missing emotion always means "no direction" — never an error,
so a job submitted without one behaves exactly as before.
"""

from __future__ import annotations

TTS_PRO_EMOTIONS = frozenset({"happy", "angry", "fear", "surprise"})

INSTRUCTIONS_MODELS = frozenset({"gpt-4o-mini-tts"})

_INSTRUCTIONS: dict[str, str] = {
    "happy": "Speak in a bright, happy tone.",
    "sad": "Speak in a sad, subdued tone.",
    "angry": "Speak in an angry, forceful tone.",
    "fear": "Speak in a frightened, trembling tone.",
    "surprise": "Speak in a surprised, astonished tone.",
    "calm": "Speak in a calm, even tone.",
}


def tts_pro_emotion(emotion: object) -> str | None:
    return emotion if isinstance(emotion, str) and emotion in TTS_PRO_EMOTIONS else None


def instructions_for(model: str, emotion: object) -> str | None:
    if model.lower() not in INSTRUCTIONS_MODELS or not isinstance(emotion, str):
        return None
    return _INSTRUCTIONS.get(emotion)
