import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from engine.conversionEngine import ConversionEngine


def _build_enabled_generators(s: dict) -> list[str]:
    result: list[str] = []
    for block in s.get("blockPriority", ["markitdown", "ocr", "ai"]):
        if block == "markitdown" and s.get("useMarkitdown", True):
            result.append("markitdown")
        elif block == "ocr" and s.get("useOcr", False):
            for eid in s.get("ocrPriority", ["tesseract"]):
                result.append(eid)
        elif block == "ai" and s.get("useAi", False):
            if not s.get("aiImprove", False) and not s.get("aiAutoDetect", False):
                result.append("gemini")
    return result or ["markitdown"]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert.py <file_path> [settings_json]")
        sys.exit(1)

    file_path = sys.argv[1]
    try:
        s = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    except json.JSONDecodeError as e:
        print(f"Error: Invalid settings JSON: {e}")
        sys.exit(1)

    use_ai = s.get("useAi", False)

    engine = ConversionEngine(
        enabled_generators=_build_enabled_generators(s),
        ai_improve=use_ai and s.get("aiImprove", False),
        ai_auto_detect=use_ai and s.get("aiAutoDetect", False),
        api_key=s.get("geminiApiKey") or None,
        model_name=s.get("modelName", "gemini-2.0-flash-lite-preview-02-05"),
        prompt_override=s.get("promptOverride", ""),
        azure_ocr_key=s.get("azureOcrKey") or None,
        azure_ocr_endpoint=s.get("azureOcrEndpoint") or None,
        tesseract_lang=s.get("tesseractLang", "deu+eng"),
    )
    print(engine.convert(file_path))
