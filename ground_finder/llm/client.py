from __future__ import annotations

import os
from functools import lru_cache

import anthropic

MODEL = "claude-sonnet-4-6"


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
