import os
from markitdown import MarkItDown
from dotenv import load_dotenv
import google.generativeai as genai

class ConversionEngine:
    def __init__(self, api_key=None):
        if api_key:
            self.api_key = api_key
        else:
            load_dotenv()
            self.api_key = os.getenv("GEMINI_API_KEY")
        
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.md = MarkItDown(llm_client=genai.GenerativeModel("gemini-1.5-flash"), llm_model="gemini-1.5-flash")
        else:
            self.md = MarkItDown()

    def convert(self, file_path):
        try:
            result = self.md.convert(file_path)
            return result.text_content
        except Exception as e:
            return f"Error: {str(e)}"

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        engine = ConversionEngine()
        print(engine.convert(sys.argv[1]))
    else:
        print("Usage: python conversionEngine.py <file_path>")
