import json
import os
import sys

# The build process bundles the shared engine beside this wrapper.
sys.path.insert(0, os.path.dirname(__file__))

from engine.conversionEngine import ConversionEngine


def _build_generator_priority(settings: dict) -> list[str]:
    """Translate mode + options into a generator_priority list for the engine."""
    mode = settings.get("mode", "simple")
    if mode == "simple":
        return ["standard"]
    if mode == "ocr":
        ocr = list(settings.get("ocrPriority", ["tesseract"]))
        return ocr if ocr else ["tesseract", "standard"]
    if mode == "ai_enhanced":
        ai_mode = settings.get("aiMode", "fallback")
        ocr = list(settings.get("ocrPriority", ["tesseract"]))
        if ai_mode == "enhancement":
            return ["gemini"] + ocr
        else:
            return ocr + ["gemini"]
    return ["standard"]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert.py <file_path> [settings_json]")
        sys.exit(1)

    file_path = sys.argv[1]
    try:
        settings = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    except json.JSONDecodeError as error:
        print(f"Error: Invalid conversion settings: {error}")
        sys.exit(1)

    mode = settings.get("mode", "simple")
    ai_mode = settings.get("aiMode", "fallback") if mode == "ai_enhanced" else "fallback"
    generator_priority = _build_generator_priority(settings)

    engine = ConversionEngine(
        api_key=settings.get("apiKey"),
        model_name=settings.get("modelName", "gemini-2.0-flash-lite-preview-02-05"),
        prompt_override=settings.get("promptOverride", ""),
        generator_priority=generator_priority,
        ai_mode=ai_mode,
        azure_ocr_key=settings.get("azureOcrKey") or None,
        azure_ocr_endpoint=settings.get("azureOcrEndpoint") or None,
        tesseract_lang=settings.get("tesseractLang", "deu+eng"),
    )
    print(engine.convert(file_path))
