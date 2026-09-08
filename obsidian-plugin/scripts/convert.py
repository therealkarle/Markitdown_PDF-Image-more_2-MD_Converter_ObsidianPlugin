import json
import os
import sys

# The build process bundles the shared engine beside this wrapper.
sys.path.insert(0, os.path.dirname(__file__))

from engine.conversionEngine import ConversionEngine

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

    engine = ConversionEngine(
        api_key=settings.get("apiKey"),
        model_name=settings.get("modelName", "gemini-2.0-flash-lite-preview-02-05"),
        prompt_override=settings.get("promptOverride", ""),
        generator_priority=settings.get("generatorPriority", ["gemini", "standard"]),
    )
    print(engine.convert(file_path))
