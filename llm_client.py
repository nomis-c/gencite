"""One LLM call -> validated Pydantic object. Used by the synthesizer and verifier layer 2.

Works with any OpenAI-compatible endpoint (DeepSeek, Groq, Gemini, ...).
role="synth" reads LLM_* from .env, role="judge" reads JUDGE_* and falls back to LLM_*.
"""
import json
import os
import re
import time

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()


class LLMOutputError(Exception):
    pass


def _config(role: str) -> dict:
    def env(name, default=None):
        if role == "judge" and os.getenv(f"JUDGE_{name}"):
            return os.getenv(f"JUDGE_{name}")
        return os.getenv(f"LLM_{name}", default)
    return {"base_url": env("BASE_URL", "https://api.deepseek.com"),
            "model": env("MODEL", "deepseek-chat"),
            "api_key": env("API_KEY")}


def chat(prompt: str, system: str = "", role: str = "synth", temperature: float = 0.0) -> str:
    """One chat completion in JSON mode. Returns the raw message content."""
    from openai import OpenAI, RateLimitError  # lazy import so --dry-run works without it
    cfg = _config(role)
    if not cfg["api_key"]:
        raise LLMOutputError(f"No API key for role '{role}' - set LLM_API_KEY in .env")
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    for attempt in range(4):  # free tiers allow few requests per minute: wait and retry
        try:
            out = client.chat.completions.create(model=cfg["model"], messages=messages,
                                                 temperature=temperature,
                                                 response_format={"type": "json_object"})
            return out.choices[0].message.content
        except RateLimitError:
            if attempt == 3:
                raise
            time.sleep(15 * (attempt + 1))


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)  # some models wrap JSON in fences
    return m.group(1) if m else raw


def llm_json(prompt: str, system: str, model: type[BaseModel], role: str = "synth") -> BaseModel:
    """Call the LLM and validate. On bad output retry once with the error appended."""
    raw = chat(prompt, system=system, role=role)
    try:
        return model.model_validate_json(_extract_json(raw))
    except (ValidationError, json.JSONDecodeError) as err:
        retry = (f"{prompt}\n\nYour previous answer was invalid:\n{raw[:2000]}\n\n"
                 f"Validation error:\n{err}\n\nReturn corrected JSON only.")
        raw2 = chat(retry, system=system, role=role)
        try:
            return model.model_validate_json(_extract_json(raw2))
        except (ValidationError, json.JSONDecodeError) as err2:
            raise LLMOutputError(str(err2)) from err2
