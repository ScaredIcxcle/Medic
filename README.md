# Medic
AI Assisted Bookkeeping for Medical Usecases

An autonomous AI worker that finds a person's receipts/invoices across simulated email and WhatsApp sources, filters out irrelevant documents using a vision model, extracts billing amounts via a separate amount-detection pipeline, and answers the user's natural-language question about what they paid or owe.

## Setup (Windows PowerShell)

### 1. Install dependencies
```powershell
pip install -r requirements.txt
```

### 2. Set API keys (required every new PowerShell window)
```powershell
$env:GROQ_VISION_API_KEY='your-groq-key-here'
$env:GEMINI_API_KEY='your-gemini-key-here'
```
- Get a free Groq key at https://console.groq.com/keys
- Get a free Gemini key at https://aistudio.google.com/apikey

### 3. Folder structure
Place simulated data like this:

emails/<name>/attachments/ ← JPG, PNG, or WEBP images
whatsapp/<name>/ ← JPG, PNG, or WEBP images (no subfolder)


## Run

**Window 1 — start the amount detector** (separate project, see its own README):
```powershell
python -m uvicorn app:app
```

**Window 2 — run the agent:**
```powershell
python agent.py
```

At the prompt, type a query in this format:

{"jason"} hey, can you find me how much balance is remaining for jason to pay?


The name in `{"..."}` is used only to locate files; the rest of the sentence is passed to the LLM as the actual question, so you can ask for total, paid, due, or balance remaining — the LLM interprets intent from the natural question, not a fixed keyword.

## Architecture

User query: {"name"} <natural language question>
↓
Hardcoded regex extracts: name, full question
↓
Retriever: collects all image files from emails/<name>/attachments/ and whatsapp/<name>/
↓
Classifier (per file):
→ Groq vision (Qwen/Qwen3.8-27B) checks "is this a billing document?"
→ If Groq is rate-limited, falls back to Gemini vision automatically
→ confidence > 0.75 and is_receipt=True → auto-accept
→ confidence 0.5–0.75 → ask user in terminal (y/n)
→ confidence < 0.5 or is_receipt=False → silently reject
↓
Accepted files → sent one by one to the Amount Detector API (/process)
→ throttled ~21s between calls, retries once on the detector's own rate-limit guardrail
↓
Detector returns {total_bill, paid, due} per file → summed across all accepted receipts
↓
Gemini (text) receives: original question + aggregated amounts
→ answers naturally, ignoring the name mention, using only the numeric data
↓
Final answer printed to terminal


## Design decisions

- **Name extraction is hardcoded**, not LLM-based — the `{"name"}` prefix is a fixed, unambiguous marker, so a regex is faster, free, and more reliable than asking an LLM to extract it.
- **Classification and final synthesis use different providers** (Groq for vision, Gemini for text) to avoid sharing rate-limit quotas with each other and with the amount detector's own internal Groq usage.
- **Confidence-based human-in-the-loop**: documents classified between 0.5 and 0.75 confidence are shown to the user for a yes/no decision, rather than silently guessing — avoids false positives/negatives in a genuinely ambiguous middle zone.
- **No changes made to the existing amount detector** — it is used purely as an external API dependency via its documented `/process` endpoint.
- **Rate-limit resilience is handled at two levels**: the classifier falls back from Groq to Gemini on a 429/rate-limit error; the detector caller retries once (after a wait) if the detector's own internal Groq OCR call hits its documented 20-second limit.
- **No PDF support** — the simulated data set only contains JPG/PNG/WEBP images, all of which are supported by both the vision classifier and the amount detector.

## Known limitations

- Classification quality depends entirely on the vision model's judgment; it was tuned via prompt wording to treat unpaid invoices/bills as valid "receipts" (matching what the amount detector can actually extract), but edge cases in wording may still be misclassified.
- Amounts across multiple receipts are summed, not itemized. If a person has several receipts, the agent reports combined totals (e.g. total due across all receipts) rather than a per-receipt breakdown. A question like "which receipt still has a balance" or "is receipt #2 paid off" isn't answerable with the current aggregation — only the combined figure is.
- Free-tier rate limits (Groq: ~7000 ITPM; detector's own Groq usage: ~1 call per 20s) mean processing many receipts for one person can be slow due to retry/fallback waits.
- No deduplication of receipts (e.g. if the same invoice appears in both email and WhatsApp, it will be counted twice in the aggregated total).
- WhatsApp and email retrieval is purely folder-based (simulated); no real API integration.
- No persistent logging or audit trail of classification decisions — results print to terminal only, per the "few receipts among millions of docs" framing where no summary was required.

## What I'd build next with more time

- Deduplicate receipts by comparing extracted amounts + vendor/date before aggregating.
- Add a lightweight local vision fallback (e.g. via Ollama) for a third tier of resilience with zero API dependency.
- Expand WhatsApp integration to parse actual chat exports (sender/timestamp) rather than assuming folder structure implies sender identity.
- Add structured logging of every classification decision and detector call for auditability.
- Support PDF inputs by rendering the first page to an image before classification.

## Assumptions

- All data (emails, WhatsApp, receipts) is simulated/mocked; no real company or personal data is used, per the assignment's constraints.
- Currency is always INR, inherited from the amount detector's own fixed convention.
- A file is a "receipt" in the broad sense of "any billing document with total/paid/due amounts," not strictly a post-payment proof of purchase — this was a deliberate scope decision to match what the amount detector is actually built to extract.
- The amount detector is already running locally on `http://localhost:8000` before the agent is run.

## Models, APIs, and frameworks used

- **Groq API** — `Qwen/Qwen3.8-27B` (vision) for primary receipt classification
- **Google Gemini API** — `gemini-3.8-flash` (vision) for classification fallback, and (text) for final answer synthesis
- **Amount Detector** — a separately built FastAPI service (own repo) for OCR + amount extraction/classification, used here as an external dependency via its `/process` endpoint
- **httpx** — HTTP client for all API calls
- **FastAPI/uvicorn** — only required to run the amount detector, not this agent itself
