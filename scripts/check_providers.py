"""
Tests every provider that has a key in .env and shows what is wrong.
Run from the project folder:   python scripts/check_providers.py
Standalone: needs only the packages you already installed. Never prints keys.
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # finds the .env in the project folder

# name: (env prefix, default base_url, default model)
PROVIDERS = {
    "gemini": (
        "GEMINI",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-2.5-flash",
    ),
    "groq": ("GROQ", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "openrouter": (
        "OPENROUTER",
        "https://openrouter.ai/api/v1",
        "meta-llama/llama-3.3-70b-instruct:free",
    ),
    "openai": ("OPENAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    "local": ("LOCAL", "http://localhost:11434/v1", "qwen2.5-coder:3b"),
}


def reason(exc: Exception) -> str:
    resp = getattr(exc, "response", None)
    text = ""
    if resp is not None:
        try:
            text = resp.text[:300]
        except Exception:
            pass
    return f"{type(exc).__name__}: {text or exc}"


for name, (prefix, default_url, default_model) in PROVIDERS.items():
    key = os.getenv(f"{prefix}_API_KEY", "ollama" if name == "local" else "").strip()
    url = os.getenv(f"{prefix}_BASE_URL", default_url).strip()
    model = os.getenv(f"{prefix}_MODEL", default_model).strip()

    print(f"\n[{name}] model={model}")
    if not key:
        print("   skipped (no key in .env)")
        continue

    client = OpenAI(api_key=key, base_url=url, timeout=60, max_retries=0)
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word OK"}],
        )
        print(f"   WORKS -> {(r.choices[0].message.content or '').strip()[:40]!r}")
    except Exception as exc:
        print(f"   FAILED -> {reason(exc)[:300]}")
        try:
            ids = sorted(m.id.removeprefix("models/") for m in client.models.list())
            print(f"   models this key can use ({len(ids)}):")
            for i in ids[:30]:
                print(f"      {i}")
            print(f"   -> copy one into {prefix}_MODEL in .env")
        except Exception as exc2:
            print(f"   could not list models either -> {reason(exc2)[:200]}")
