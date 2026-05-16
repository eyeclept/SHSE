"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Offline translation answer card service. Detects translation queries
    and calls the local Ollama instance via the standard LLM API
    /chat/completions endpoint. The model returns only the translated text;
    no surrounding explanation is included. A 15-second timeout is enforced.
    If Ollama is unreachable or the model exceeds the timeout, the card is
    silently suppressed and BM25 results render normally.
"""
# Imports
import logging
import os
import re
from typing import Optional

import requests as _requests

# Globals
logger = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds

# Detection regexes (mutually exclusive, matched in order)
_RE_TRANSLATE = re.compile(
    r"translate\s+(.+?)\s+to\s+(\w[\w\s]*)",
    re.IGNORECASE,
)
_RE_HOW_DO_YOU_SAY = re.compile(
    r"how\s+do\s+you\s+say\s+(.+?)\s+in\s+(\w[\w\s]*)",
    re.IGNORECASE,
)
_RE_WHAT_IS_IN = re.compile(
    r"what\s+is\s+(.+?)\s+in\s+(\w[\w\s]*)",
    re.IGNORECASE,
)


# Functions
def detect_translate_query(q: str) -> Optional[dict]:
    """
    Input: q — raw search query string
    Output: dict {text, target_lang} or None
    Details:
        Matches translation trigger phrases. Plain queries with no trigger
        word always return None. Strips trailing punctuation from both fields.
    """
    q = q.strip()
    for pattern in (_RE_TRANSLATE, _RE_HOW_DO_YOU_SAY, _RE_WHAT_IS_IN):
        m = pattern.search(q)
        if m:
            text = m.group(1).strip().strip("\"'")
            lang = m.group(2).strip().rstrip("?.")
            if text and lang:
                return {"text": text, "target_lang": lang}
    return None


def translate_text(text: str, target_lang: str, session=None) -> Optional[str]:
    """
    Input: text (str), target_lang (str), session (unused, for test injection)
    Output: translated string or None
    Details:
        POSTs to LLM_API_BASE/chat/completions using LLM_TRANSLATE_MODEL.
        The system prompt instructs the model to return only the translation
        with no explanation, notes, or quotation marks. Returns None on any
        failure (network error, timeout, bad JSON, missing content).
        All failures are logged at WARNING.
    """
    from flask_app.config import Config

    api_base = Config.LLM_API_BASE.rstrip("/")
    model = Config.LLM_TRANSLATE_MODEL
    url = f"{api_base}/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a translation engine. "
                    "Translate the user's text into the requested language. "
                    "Return ONLY the translation — no explanation, no notes, "
                    "no quotation marks, no extra text."
                ),
            },
            {
                "role": "user",
                "content": f"Translate into {target_lang}: {text}",
            },
        ],
        "stream": False,
    }

    requester = session or _requests
    try:
        resp = requester.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content.strip() if content else None
    except _requests.exceptions.Timeout:
        logger.warning("translate_text: request timed out after %ss (model=%s)", _TIMEOUT, model)
        return None
    except _requests.exceptions.RequestException:
        logger.warning("translate_text: network error", exc_info=True)
        return None
    except (KeyError, IndexError, ValueError):
        logger.warning("translate_text: unexpected response structure", exc_info=True)
        return None
    except Exception:
        logger.warning("translate_text: unexpected error", exc_info=True)
        return None


def build_translate_card(q: str) -> tuple:
    """
    Input: q — raw search query string
    Output: (answer_card dict, ai_context str) or (None, None)
    Details:
        Entry point for the inline dispatcher. Detects, translates, and returns
        a structured answer_card and ai_context string.
        answer_card keys: type, word, body, target_lang, source.
    """
    query = detect_translate_query(q)
    if not query:
        return None, None

    translation = translate_text(query["text"], query["target_lang"])
    if not translation:
        return None, None

    model = os.environ.get("LLM_TRANSLATE_MODEL", "aya-expanse:8b")
    answer_card = {
        "type":        "translation",
        "word":        query["text"],
        "body":        translation,
        "target_lang": query["target_lang"],
        "source":      f"Translated offline by {model}",
    }
    ai_context = f"Translation of '{query['text']}' in {query['target_lang']}: {translation}"
    return answer_card, ai_context


if __name__ == "__main__":
    pass
