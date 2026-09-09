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
            for eid in s.get(
                "ocrPriority",
                ["azure_document_intelligence", "tesseract", "azure_ocr", "win_ocr"],
            ):
                result.append(eid)
        elif block == "ai" and s.get("useAi", False):
            if not s.get("aiImprove", False) and not s.get("aiAutoDetect", False):
                result.append("gemini")
    return result or ["markitdown"]


def convert_file(file_path: str, s: dict) -> str:
    """Convert a file or raise when the engine reports a failed conversion."""

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
        azure_document_intelligence_key=s.get("azureDocumentIntelligenceKey") or None,
        azure_document_intelligence_endpoint=s.get("azureDocumentIntelligenceEndpoint") or None,
        tesseract_lang=s.get("tesseractLang", "deu+eng"),
        tesseract_cmd=s.get("tesseractCmd") or None,
    )
    result = engine.convert(file_path)
    if result.lstrip().startswith("Error:"):
        raise RuntimeError(result.strip())
    return result


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

    try:
        print(convert_file(file_path, s))
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
