import os
from markitdown import MarkItDown
from dotenv import load_dotenv

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class ConversionEngine:
    def __init__(self, api_key: str | None = None):
        if api_key:
            self.api_key = api_key
        else:
            load_dotenv()
            self.api_key = os.getenv("GEMINI_API_KEY")

        if self.api_key and GENAI_AVAILABLE:
            genai.configure(api_key=self.api_key)
            self.md = MarkItDown(
                llm_client=genai.GenerativeModel("gemini-1.5-flash"),
                llm_model="gemini-1.5-flash",
            )
        else:
            self.md = MarkItDown()

    def convert(self, file_path: str) -> str:
        try:
            result = self.md.convert(file_path)
            return result.text_content
        except Exception as e:
            return f"Error: {str(e)}"


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
