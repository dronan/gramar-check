"""
Grammar checking via OpenAI.

The model receives the text and returns a list of errors as JSON.
We ask for the exact wrong substring (not character offsets) and locate
it ourselves — this avoids the classic LLM offset-counting mistake.

Cheapest viable models (set GRAMMAR_MODEL in config.py):
  gpt-4o-mini   — default, excellent quality, ~$0.00002/check
  gpt-4.1-nano  — even cheaper, good for simple spelling/grammar
"""
import json
import re

try:
    from config import OPENAI_API_KEY, GRAMMAR_MODEL
except ImportError:
    OPENAI_API_KEY = ""
    GRAMMAR_MODEL = "gpt-4o-mini"

_SYSTEM = (
    "You are a strict grammar and spelling checker. "
    "Scan EVERY word in the text for errors. Follow these steps:\n\n"
    "STEP 1 — SPELLING: Check every single word against the English dictionary. "
    "Flag ANY word that is misspelled, even if it vaguely resembles a real word. "
    "Use category 'Spelling'.\n"
    "STEP 2 — GRAMMAR: Check for grammatical errors (agreement, tense, word choice). "
    "Use category 'Grammar'.\n"
    "STEP 3 — PUNCTUATION: Check for punctuation issues. "
    "Use category 'Punctuation'.\n"
    "STEP 4 — STYLE: Flag awkward phrasings. Use category 'Style'.\n\n"
    "Return ONLY a JSON array (no markdown, no explanation). "
    "Each item must have:\n"
    '  "error": the exact wrong substring as it appears in the input (case-sensitive),\n'
    '  "replacement": the best corrected version,\n'
    '  "message": one short sentence explaining the issue,\n'
    '  "category": exactly one of: Spelling, Grammar, Punctuation, Style.\n\n'
    "IMPORTANT:\n"
    "- Misspelled words (e.g. 'wronglym', 'appple', 'teh', 'recieve') MUST always be flagged as Spelling.\n"
    "- Do NOT skip any word that looks wrong, even if it is close to a real word.\n"
    "- Do NOT flag proper nouns, brand names, or intentional style choices.\n"
    "- If there are no errors return []."
)

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


class GrammarError:
    def __init__(self, offset: int, length: int, message: str,
                 category: str, replacements: list[str], original_word: str):
        self.offset = offset
        self.length = length
        self.message = message
        self.category = category
        self.rule_id = ""
        self.replacements = replacements
        self.original_word = original_word

    def __repr__(self):
        return (f"<GrammarError offset={self.offset} len={self.length} "
                f"word={self.original_word!r}>")


def check(text: str) -> list[GrammarError]:
    """
    Returns a list of GrammarError for the given text.
    Returns [] on API failure or if text is too short.
    """
    if len(text.strip()) < 5:
        return []
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=GRAMMAR_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=512,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if the model adds them
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        items = json.loads(raw)
    except Exception as e:
        print(f"[grammar_checker] {e}")
        return []

    print(f"[grammar] raw response: {items}")
    errors = []
    search_from = 0  # advance search position to handle duplicate substrings
    for item in items:
        error_text = item.get("error", "")
        replacement = item.get("replacement", "")
        message = item.get("message", "")
        category = item.get("category", "Grammar")

        if not error_text or error_text == replacement:
            continue

        idx = text.find(error_text, search_from)
        if idx == -1:
            # Try from the beginning (out-of-order response)
            idx = text.find(error_text)
        if idx == -1:
            print(f"[grammar_checker] could not locate {error_text!r} in text")
            continue

        # ── Heuristic: force Spelling when it looks like a typo ───────────
        # If both error and replacement are single words and their edit distance
        # is small (≤ 2 edits OR ≤ 40% of the longer word), it's almost certainly
        # a spelling mistake regardless of what the LLM categorized it as.
        if category != "Spelling" and " " not in error_text and " " not in replacement:
            category = _spelling_heuristic(error_text, replacement) or category

        errors.append(GrammarError(
            offset=idx,
            length=len(error_text),
            message=message,
            category=category,
            replacements=[replacement] if replacement else [],
            original_word=error_text,
        ))
        search_from = idx + len(error_text)

    return errors


def _spelling_heuristic(error: str, replacement: str) -> str | None:
    """Return 'Spelling' if error looks like a typo of replacement, else None."""
    a, b = error.lower(), replacement.lower()
    if a == b:
        return None
    # Simple edit distance (Levenshtein)
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            temp = dp[j]
            dp[j] = prev if a[i-1] == b[j-1] else 1 + min(prev, dp[j], dp[j-1])
            prev = temp
    dist = dp[n]
    threshold = max(2, int(max(m, n) * 0.45))
    return "Spelling" if dist <= threshold else None

