import os
import re
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

from retriever import retrieve_files
from classifier import classify_receipt, process_file_with_user_prompt
from detector_caller import call_detector_batch, aggregate_detector_results


GEMINI_MODEL = "gemini-3.8-flash"


def extract_name_and_query(user_input):
    """
    Example:
      '{"jason"} hey, how much balance is remaining for jason to pay?'
      -> ("jason", "hey, how much balance is remaining for jason to pay?")
    """
    match = re.match(r'\{"([^"]+)"\}\s*(.*)', user_input.strip())
    if match:
        return match.group(1), match.group(2)
    return None, user_input


def classify_and_filter_receipts(file_paths, groq_api_key, gemini_api_key):
    """Classify files as receipts. >0.75 auto-accept, 0.5-0.75 ask user, <0.5 reject."""
    accepted = []

    for file_path in file_paths:
        filename = file_path.split("\\")[-1].split("/")[-1]
        print(f"\n  Checking: {filename}")

        result = classify_receipt(file_path, groq_api_key, gemini_api_key)
        confidence = result.get("confidence", 0)
        is_receipt = result.get("is_receipt", False)
        reasoning = result.get("reasoning", "")

        print(f"    → {reasoning}")

        if confidence > 0.75 and is_receipt:
            print(f"    ✓ Accepted as billing document (confidence {confidence:.2f})")
            accepted.append(file_path)
        elif 0.5 <= confidence <= 0.75:
            print(f"    ? Uncertain (confidence {confidence:.2f}) — asking for confirmation")
            if process_file_with_user_prompt(file_path):
                accepted.append(file_path)
        else:
            print(f"    ✗ Rejected (confidence {confidence:.2f})")

    return accepted


def call_llm_for_answer(question, total_bill, paid, due, gemini_api_key):
    """Send the question + extracted amounts to Gemini for final answer."""
    prompt = (
        f"User question: {question}\n\n"
        f"Extracted financial data from receipts:\n"
        f"- Total bill: {total_bill} INR\n"
        f"- Amount paid: {paid} INR\n"
        f"- Amount due: {due} INR\n\n"
        "Answer the user's question naturally based on this data. "
        "Disregard any specific name mentioned in the question; just answer using the numbers."
    )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={gemini_api_key}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        response = httpx.post(url, json=payload, timeout=30.0)
        result = response.json()
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"Error calling Gemini: {str(e)}"


def main():
    groq_api_key = os.getenv("GROQ_VISION_API_KEY")
    gemini_api_key = os.getenv("GEMINI_API_KEY")

    if not groq_api_key or not gemini_api_key:
        print("Error: set GROQ_VISION_API_KEY and GEMINI_API_KEY environment variables")
        sys.exit(1)

    user_input = input("Query: ").strip()
    if not user_input:
        print("No input provided")
        return

    name, question = extract_name_and_query(user_input)
    if not name:
        print('Error: query must start with {"name"}')
        return

    print(f"\n[1/4] Understood goal: find billing info for '{name}' to answer — \"{question}\"")

    print(f"\n[2/4] Searching emails and WhatsApp for files belonging to '{name}'...")
    files = retrieve_files(name)
    if not files:
        print(f"  No files found for {name}")
        return
    print(f"  Found {len(files)} file(s) to examine")

    print(f"\n[3/4] Classifying each file as a billing document or not...")
    accepted_receipts = classify_and_filter_receipts(files, groq_api_key, gemini_api_key)
    if not accepted_receipts:
        print("\n  No receipts found after classification")
        return
    print(f"\n  {len(accepted_receipts)} file(s) confirmed as billing documents")

    print(f"\n[4/4] Extracting amounts from confirmed documents...")
    detector_results = call_detector_batch(accepted_receipts)
    aggregated = aggregate_detector_results(detector_results)
    print(f"  Total bill: {aggregated['total_bill']} | Paid: {aggregated['paid']} | Due: {aggregated['due']}")
    print(f"  ({aggregated['receipt_count']} document(s) successfully processed)")

    print(f"\nSynthesizing answer...")
    answer = call_llm_for_answer(
        question,
        aggregated['total_bill'],
        aggregated['paid'],
        aggregated['due'],
        gemini_api_key
    )

    print(f"\n{'='*50}")
    print(f"ANSWER: {answer}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()