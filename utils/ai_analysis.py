# בתוך הקובץ utils/ai_analysis.py

    # ... קוד קודם ...

    # Basic parsing of response
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    result: Dict[str, float] = {}
    for line in lines:
        upper = line.upper()
        if upper.startswith("BUY") or upper.startswith("SELL") or upper.startswith("HOLD"):
            result["signal"] = line.split()[0]

        lower = line.lower()
        if "confidence" in lower:
            import re
            match = re.search(r"(\d+(\.\d+)?)", line)
            if match:
                result["confidence"] = float(match.group(1))

    return result



