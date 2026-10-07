import time
from pathlib import Path
import httpx

DETECTOR_DELAY_SECONDS = 21  # README: detector's own Groq call needs ~20s between images
RETRY_DELAY_SECONDS = 30     # README: on failure, wait ~30s and retry


def call_detector(file_path, detector_url="http://localhost:8000/process"):
    """
    Call the amount detector API with a receipt image.
    Retries once if the detector reports its known rate-limit failure.

    Returns: {
        "total_bill": int or None,
        "paid": int or None,
        "due": int or None,
        "status": "ok" or "error"
    }
    """
    file_path = Path(file_path)

    def _post_once():
        with open(file_path, 'rb') as f:
            files = {'file': (file_path.name, f.read())}
        response = httpx.post(detector_url, files=files, timeout=30.0)
        return response.json()

    try:
        result = _post_once()

        if result.get("status") == "no_amounts_found" and result.get("reason") == "image could not be read":
            time.sleep(RETRY_DELAY_SECONDS)
            result = _post_once()

        if result.get("status") == "ok" and "amounts" in result:
            extracted = {"total_bill": None, "paid": None, "due": None, "status": "ok"}
            for amount in result["amounts"]:
                amount_type = amount.get("type")
                value = amount.get("value")
                if amount_type in extracted:
                    extracted[amount_type] = value
            return extracted
        else:
            return {"total_bill": None, "paid": None, "due": None, "status": "error"}

    except Exception as e:
        return {"total_bill": None, "paid": None, "due": None, "status": f"error: {str(e)}"}


def call_detector_batch(file_paths, detector_url="http://localhost:8000/process"):
    """
    Call the detector for multiple receipts, throttled to respect its
    internal ~20s Groq rate limit between calls.

    Returns: list of result dicts, same order as file_paths.
    """
    results = []
    for i, file_path in enumerate(file_paths):
        if i > 0:
            time.sleep(DETECTOR_DELAY_SECONDS)
        results.append(call_detector(file_path, detector_url))
    return results


def aggregate_detector_results(results_list):
    """
    Aggregate results from multiple receipt detections.

    Returns: {
        "total_bill": sum or None,
        "paid": sum or None,
        "due": sum or None,
        "receipt_count": number of receipts processed
    }
    """
    totals = {"total_bill": 0, "paid": 0, "due": 0}
    count = 0

    for result in results_list:
        if result.get("status") == "ok":
            count += 1
            if result.get("total_bill") is not None:
                totals["total_bill"] += result["total_bill"]
            if result.get("paid") is not None:
                totals["paid"] += result["paid"]
            if result.get("due") is not None:
                totals["due"] += result["due"]

    return {
        "total_bill": totals["total_bill"] if totals["total_bill"] > 0 else None,
        "paid": totals["paid"] if totals["paid"] > 0 else None,
        "due": totals["due"] if totals["due"] > 0 else None,
        "receipt_count": count
    }