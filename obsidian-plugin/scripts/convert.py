import sys
import os
from markitdown import MarkItDown
from dotenv import load_dotenv
import google.generativeai as genai

def convert(file_path, api_key=None):
    if api_key:
        genai.configure(api_key=api_key)
        md = MarkItDown(llm_client=genai.GenerativeModel("gemini-1.5-flash"), llm_model="gemini-1.5-flash")
    else:
        md = MarkItDown()
    
    try:
        result = md.convert(file_path)
        return result.text_content
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert.py <file_path> [api_key]")
        sys.exit(1)
    
    file_path = sys.argv[1]
    api_key = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(convert(file_path, api_key))
