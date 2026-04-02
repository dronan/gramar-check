"""
OpenAI-backed text operations: fix grammar, translate, rewrite, complete.
"""
from openai import OpenAI
from config import OPENAI_API_KEY, TARGET_LANGUAGE, MODEL

_client = OpenAI(api_key=OPENAI_API_KEY)


def _call(system_prompt: str, user_text: str) -> str:
    response = _client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


def fix_grammar(text: str) -> str:
    return _call(
        "Corrija apenas os erros gramaticais e ortográficos do texto a seguir. "
        "Mantenha o estilo, voz e intenção originais do autor. "
        "Retorne apenas o texto corrigido, sem explicações.",
        text,
    )


def translate(text: str, target: str = TARGET_LANGUAGE) -> str:
    return _call(
        f"Traduza o texto a seguir para {target}. "
        "Mantenha o tom e o estilo original. "
        "Retorne apenas a tradução, sem explicações.",
        text,
    )


def rewrite(text: str) -> str:
    return _call(
        "Reescreva o texto a seguir de forma mais clara, fluente e profissional, "
        "preservando o significado original. "
        "Retorne apenas o texto reescrito, sem explicações.",
        text,
    )


def check_grammar(text: str) -> str | None:
    """
    Returns corrected text if there are grammar/spelling errors, None if already correct.
    Uses a single API call that returns NO_ERRORS when the text is fine.
    Skips very short strings (< 8 chars) to avoid noise.
    """
    if len(text.strip()) < 8:
        return None
    result = _call(
        "You are a grammar and spelling checker. "
        "If the following text contains grammar, spelling, or punctuation errors, "
        "return only the fully corrected version. "
        "If the text is already correct, return exactly the string: NO_ERRORS. "
        "Do not add explanations.",
        text,
    )
    if result.strip().upper() == "NO_ERRORS":
        return None
    if result.strip() == text.strip():
        return None
    return result.strip()


def complete(text: str) -> str:
    return _call(
        "Continue o texto a seguir de forma natural e coerente, "
        "mantendo o estilo e o tom do autor. "
        "Retorne o texto original seguido da continuação, sem explicações.",
        text,
    )
