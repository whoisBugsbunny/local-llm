"""
Basic checks on AI-written UI code (tsx / html / js).

This is NOT a real sandbox. Real protection is on the frontend:
render generated code inside <iframe sandbox="allow-scripts"> (no allow-same-origin)
and pass the data in with postMessage. This guard just rejects the obvious bad stuff.
"""
import re

_BAD_PATTERNS = [
    r"\bfetch\s*\(", r"XMLHttpRequest", r"\bWebSocket\b", r"navigator\.sendBeacon",
    r"\beval\s*\(", r"new\s+Function", r"\bimportScripts\b", r"\bimport\s*\(",
    r"document\.cookie", r"localStorage", r"sessionStorage",
    r"window\.(top|parent)", r"<script[^>]+src\s*=", r"from\s+['\"]https?:",
]


class CodeRejected(ValueError):
    pass


def validate_code(code: str) -> None:
    if not code.strip():
        raise CodeRejected("Empty code")
    for pattern in _BAD_PATTERNS:
        if re.search(pattern, code, re.I):
            raise CodeRejected(f"Generated code uses a forbidden feature: {pattern}")


def strip_fences(text: str) -> str:
    """Models love wrapping code in ```tsx ... ```; remove that."""
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n", "", text)
    text = re.sub(r"\n```$", "", text)
    return text.strip()
