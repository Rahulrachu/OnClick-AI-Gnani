"""Voice layer: speak to OnClick AI in Indian languages (Gnani Prisma STT + Timbre TTS)."""
from .gnani import LANGUAGES, GnaniError, synthesize, transcribe

__all__ = ["LANGUAGES", "GnaniError", "synthesize", "transcribe"]
