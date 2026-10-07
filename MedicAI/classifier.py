import base64
import json
from pathlib import Path
import httpx

GROQ_VISION_MODEL = "Qwen/Qwen3.8-27B"
GEMINI_MODEL = "gemini-3.8-flash"

CLASSIFY_PROMPT = (
    "Is this a financial billing document — a receipt, invoice, or bill that "
    "states a total amount, amount paid, and/or amount due/balance (whether or "
    "not it has been paid yet)? Say yes even if the balance due is unpaid — an "
    "unpaid invoice still counts. Say no only for non-financial documents like "
    "insurance forms, prescriptions, medical/photo images, or internal memos "
    "that don't contain billing amounts. Respond ONLY with raw JSON, no "
    'markdown: {"is_receipt": true/false, "confidence": 0.0-1.0, "reasoning": "short reason"}'
)


def encode_file_to_base64(file_path):
    """Read an image file and return base64-encoded content + media type."""
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix in ['.jpg', '.jpeg']:
        media_type = 'image/jpeg'
    elif suffix == '.png':
        media_type = 'image/png'
    elif suffix == '.webp':
        media_type = 'image/webp'
    else:
        return None, None

    with open(file_path, 'rb') as f:
        data = base64.standard_b64encode(f.read()).decode('utf-8')

    return data, media_type


def _classify_with_groq(data, media_type, groq_api_key):
    """Returns (result_dict, was_rate_limited)."""
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": CLASSIFY_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}},
                ],
            }
        ],
        "max_tokens": 200,
        "temperature": 0,
    }

    response = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        json=payload,
        headers=headers,
        timeout=30.0,
    )
    result = response.json()

    if "error" in result:
        was_rate_limited = result["error"].get("code") == "rate_limit_exceeded"
        return None, was_rate_limited

    text = result["choices"][0]["message"]["content"]
    text = text.strip().strip("```json").strip("```").strip()
    return json.loads(text), False


def _classify_with_gemini(data, media_type, gemini_api_key):
    """Fallback classifier using Gemini vision."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={gemini_api_key}"
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": CLASSIFY_PROMPT},
                {"inline_data": {"mime_type": media_type, "data": data}},
            ]
        }]
    }

    response = httpx.post(url, json=payload, timeout=30.0)
    result = response.json()

    text = result["candidates"][0]["content"]["parts"][0]["text"]
    text = text.strip().strip("```json").strip("```").strip()
    return json.loads(text)


def classify_receipt(file_path, groq_api_key, gemini_api_key=None):
    """
    Classify if a file is a financial billing document (receipt/invoice/bill).
    Tries Groq first; falls back to Gemini if Groq is rate-limited.

    Returns: {"is_receipt": bool, "confidence": float, "reasoning": str}
    """
    data, media_type = encode_file_to_base64(file_path)
    if data is None:
        return {"is_receipt": False, "confidence": 0.0, "reasoning": "Unsupported file type"}

    try:
        result, was_rate_limited = _classify_with_groq(data, media_type, groq_api_key)
        if result is not None:
            return result
        if was_rate_limited and gemini_api_key:
            return _classify_with_gemini(data, media_type, gemini_api_key)
        return {"is_receipt": False, "confidence": 0.0, "reasoning": "Groq error, no Gemini fallback available"}
    except Exception as e:
        if gemini_api_key:
            try:
                return _classify_with_gemini(data, media_type, gemini_api_key)
            except Exception as e2:
                return {"is_receipt": False, "confidence": 0.0, "reasoning": f"Error: {str(e2)}"}
        return {"is_receipt": False, "confidence": 0.0, "reasoning": f"Error: {str(e)}"}


def process_file_with_user_prompt(file_path):
    """For 0.5-0.75 confidence: ask user in terminal if this is a receipt."""
    filename = Path(file_path).name
    response = input(f"  Is '{filename}' a receipt? (y/n): ").strip().lower()
    return response == 'y'