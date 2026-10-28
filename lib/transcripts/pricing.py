"""Token counts in US dollars at list price, from the model rates T3 keeps in litellm's format."""
from __future__ import annotations

import json
import re
from pathlib import Path

RATES = Path.home() / ".t3" / "userdata" / "usage-model-rates.json"
PREFIXES = ("", "anthropic.", "anthropic/", "openai/")
# A dated snapshot (-20260901) or a context tag ([1m]) that the rates file leaves off.
SUFFIX = re.compile(r"-\d{8}$|\[.*\]$")


def load():
    """model -> rate entry; empty when this machine has no rates file, so nothing gets a price."""
    try:
        text = RATES.read_text()
    except FileNotFoundError:
        return {}
    return json.loads(text)["document"]


def rate(rates, model):
    for name in dict.fromkeys((model, SUFFIX.sub("", model))):
        for prefix in PREFIXES:
            if prefix + name in rates:
                return rates[prefix + name]
    return None


def cost(rates, model, tokens):
    """The tokens' price, or None for a model the rates do not price per input and output token."""
    entry = rate(rates, model)
    if entry is None or not {"input_cost_per_token", "output_cost_per_token"} <= entry.keys():
        return None
    per_input = entry["input_cost_per_token"]
    return (tokens.fresh * per_input
            + tokens.write * entry.get("cache_creation_input_token_cost", per_input * 1.25)
            + tokens.read * entry.get("cache_read_input_token_cost", per_input * 0.1)
            + tokens.out * entry["output_cost_per_token"])
