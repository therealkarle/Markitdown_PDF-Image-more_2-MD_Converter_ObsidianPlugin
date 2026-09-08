import os
from markitdown import MarkItDown
from dotenv import load_dotenv

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class ConversionEngine:
    """Converts documents using the configured generator priority order."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.0-flash-lite-preview-02-05",
        prompt_override: str = "",
        generator_priority: list[str] | None = None,
    ):
        load_dotenv()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.prompt_override = prompt_override
        self.generator_priority = generator_priority or ["gemini", "standard"]

    def _create_converter(self, generator: str) -> MarkItDown:
        if generator == "gemini":
            if not self.api_key:
                raise RuntimeError("No Gemini API key configured.")
            if not GENAI_AVAILABLE:
                raise RuntimeError("The google-generativeai package is not installed.")

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(
                self.model_name,
                system_instruction=self.prompt_override or None,
            )
            return MarkItDown(llm_client=model, llm_model=self.model_name)

        if generator == "standard":
            return MarkItDown()

        raise RuntimeError(f"Unknown Markdown generator: {generator}")

    def convert(self, file_path: str) -> str:
        errors: list[str] = []
        for generator in self.generator_priority:
            try:
                return self._create_converter(generator).convert(file_path).text_content
            except Exception as error:
                errors.append(f"{generator}: {error}")

        return "Error: Conversion failed. " + " | ".join(errors)


# CLI entry point — lets the engine be called directly:
# python -m engine.conversionEngine <file_path> [api_key]
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m engine.conversionEngine <file_path> [api_key]")
        sys.exit(1)

    file_path = sys.argv[1]
    key = sys.argv[2] if len(sys.argv) > 2 else None
    engine = ConversionEngine(api_key=key)
    print(engine.convert(file_path))
