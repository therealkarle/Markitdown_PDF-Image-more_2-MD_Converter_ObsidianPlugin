import os
import sys
import platform
from pathlib import Path
from markitdown import MarkItDown
from dotenv import load_dotenv

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

try:
    import pytesseract
    from PIL import Image
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    from azure.ai.vision.imageanalysis import ImageAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    AZURE_OCR_AVAILABLE = True
except ImportError:
    AZURE_OCR_AVAILABLE = False

WIN_OCR_AVAILABLE = False
if platform.system() == "Windows":
    try:
        import winrt.windows.media.ocr as win_ocr_api
        import winrt.windows.globalization as globalization
        import winrt.windows.graphics.imaging as imaging
        import asyncio
        WIN_OCR_AVAILABLE = True
    except ImportError:
        pass

try:
    import pdf2image
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False


def _pdf_to_images(file_path: str) -> list:
    """Convert a PDF to a list of PIL Images. Falls back to treating as image."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        if not PDF2IMAGE_AVAILABLE:
            raise RuntimeError("pdf2image is not installed. Install it to use OCR on PDFs.")
        return pdf2image.convert_from_path(file_path)
    # For image files, open directly
    from PIL import Image as PILImage
    return [PILImage.open(file_path)]


class ConversionEngine:
    """Converts documents using the configured generator priority order.

    Modes:
        simple      — MarkItDown native (default, no OCR)
        ocr         — OCR engines in fallback chain (tesseract / azure_ocr / win_ocr)
        ai_enhanced — OCR/standard + optional Gemini AI pass

    ai_mode (only relevant when 'gemini' is in generator_priority or mode=ai_enhanced):
        fallback    — Gemini at end of chain, used only if all others fail
        enhancement — Gemini runs after the first successful conversion to improve it
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.0-flash-lite-preview-02-05",
        prompt_override: str = "",
        generator_priority: list[str] | None = None,
        ai_mode: str = "fallback",
        azure_ocr_key: str | None = None,
        azure_ocr_endpoint: str | None = None,
        tesseract_lang: str = "deu+eng",
    ):
        load_dotenv()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.prompt_override = prompt_override
        self.generator_priority = generator_priority or ["standard"]
        self.ai_mode = ai_mode  # "fallback" | "enhancement"
        self.azure_ocr_key = azure_ocr_key or os.getenv("AZURE_OCR_KEY")
        self.azure_ocr_endpoint = azure_ocr_endpoint or os.getenv("AZURE_OCR_ENDPOINT")
        self.tesseract_lang = tesseract_lang

    # ---------------------------------------------------------------- converters

    def _convert_with_gemini(self, file_path: str) -> str:
        if not self.api_key:
            raise RuntimeError("No Gemini API key configured.")
        if not GENAI_AVAILABLE:
            raise RuntimeError("The google-generativeai package is not installed.")
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(
            self.model_name,
            system_instruction=self.prompt_override or None,
        )
        md = MarkItDown(llm_client=model, llm_model=self.model_name)
        return md.convert(file_path).text_content

    def _convert_with_standard(self, file_path: str) -> str:
        return MarkItDown().convert(file_path).text_content

    def _convert_with_tesseract(self, file_path: str) -> str:
        if not TESSERACT_AVAILABLE:
            raise RuntimeError("pytesseract or Pillow is not installed.")
        images = _pdf_to_images(file_path)
        pages = [pytesseract.image_to_string(img, lang=self.tesseract_lang) for img in images]
        return "\n\n---\n\n".join(pages)

    def _convert_with_azure_ocr(self, file_path: str) -> str:
        if not AZURE_OCR_AVAILABLE:
            raise RuntimeError("azure-ai-vision-imageanalysis is not installed.")
        if not self.azure_ocr_key or not self.azure_ocr_endpoint:
            raise RuntimeError("Azure OCR key and endpoint must be configured.")
        client = ImageAnalysisClient(
            endpoint=self.azure_ocr_endpoint,
            credential=AzureKeyCredential(self.azure_ocr_key),
        )
        suffix = Path(file_path).suffix.lower()
        if suffix == ".pdf":
            # Azure Vision doesn't support PDF directly — convert pages first
            images = _pdf_to_images(file_path)
            results = []
            for img in images:
                import io
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                result = client.analyze(
                    image_data=buf.getvalue(),
                    visual_features=["READ"],
                )
                if result.read:
                    results.append("\n".join(line.text for block in result.read.blocks for line in block.lines))
            return "\n\n---\n\n".join(results)
        else:
            with open(file_path, "rb") as f:
                data = f.read()
            result = client.analyze(image_data=data, visual_features=["READ"])
            if result.read:
                return "\n".join(line.text for block in result.read.blocks for line in block.lines)
            return ""

    def _convert_with_win_ocr(self, file_path: str) -> str:
        if not WIN_OCR_AVAILABLE:
            raise RuntimeError(
                "Windows OCR is not available. Requires Windows 10 1803+ and the winrt package."
            )

        async def _run_win_ocr(path: str) -> str:
            images = _pdf_to_images(path)
            results = []
            engine = win_ocr_api.OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                raise RuntimeError("Could not create Windows OCR engine.")
            for pil_img in images:
                import io
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                buf.seek(0)
                stream = imaging.BitmapDecoder.create_async(
                    winrt.windows.storage.streams.InMemoryRandomAccessStream()
                )
                # Use winrt SoftwareBitmap from PIL via bytes
                bmp_data = buf.getvalue()
                iras = winrt.windows.storage.streams.InMemoryRandomAccessStream()
                writer = winrt.windows.storage.streams.DataWriter(iras)
                writer.write_bytes(list(bmp_data))
                await writer.store_async()
                iras.seek(0)
                decoder = await imaging.BitmapDecoder.create_async(iras)
                soft_bmp = await decoder.get_software_bitmap_async()
                ocr_result = await engine.recognize_async(soft_bmp)
                results.append(ocr_result.text)
            return "\n\n---\n\n".join(results)

        return asyncio.run(_run_win_ocr(file_path))

    def _run_generator(self, generator: str, file_path: str) -> str:
        if generator == "standard":
            return self._convert_with_standard(file_path)
        if generator == "gemini":
            return self._convert_with_gemini(file_path)
        if generator == "tesseract":
            return self._convert_with_tesseract(file_path)
        if generator == "azure_ocr":
            return self._convert_with_azure_ocr(file_path)
        if generator == "win_ocr":
            return self._convert_with_win_ocr(file_path)
        raise RuntimeError(f"Unknown generator: {generator}")

    # ---------------------------------------------------------------- public API

    def convert(self, file_path: str) -> str:
        """Convert file_path to Markdown.

        - Iterates generator_priority as a fallback chain.
        - If ai_mode == "enhancement" and "gemini" is NOT already the first entry,
          Gemini runs after the first successful result to improve the text.
        """
        errors: list[str] = []

        # Separate gemini from the chain when running in enhancement mode
        non_ai_chain = [g for g in self.generator_priority if g != "gemini"]
        has_gemini = "gemini" in self.generator_priority
        run_enhancement = self.ai_mode == "enhancement" and has_gemini

        # Primary chain (all generators when fallback, non-AI generators when enhancement)
        primary_chain = non_ai_chain if run_enhancement else self.generator_priority

        base_result: str | None = None
        for generator in primary_chain:
            try:
                base_result = self._run_generator(generator, file_path)
                break
            except Exception as error:
                errors.append(f"{generator}: {error}")

        # Enhancement pass: feed base result into Gemini for improvement
        if run_enhancement and base_result is not None:
            try:
                enhance_prompt = (
                    self.prompt_override
                    or "You are a document formatting assistant. "
                    "Clean up and improve the following OCR/extracted text into well-structured Markdown. "
                    "Fix OCR errors, restore formatting, keep all content. "
                    "Return only the improved Markdown."
                )
                if not self.api_key:
                    raise RuntimeError("No Gemini API key configured for enhancement.")
                if not GENAI_AVAILABLE:
                    raise RuntimeError("google-generativeai not installed.")
                genai.configure(api_key=self.api_key)
                model = genai.GenerativeModel(
                    self.model_name,
                    system_instruction=enhance_prompt,
                )
                response = model.generate_content(base_result)
                return response.text
            except Exception as error:
                errors.append(f"gemini-enhancement: {error}")
                # Fall through: return the base result even if AI enhancement failed
                return base_result

        if base_result is not None:
            return base_result

        return "Error: Conversion failed. " + " | ".join(errors)


# CLI entry point:
# python -m engine.conversionEngine <file_path> [api_key]
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m engine.conversionEngine <file_path> [api_key]")
        sys.exit(1)

    file_path = sys.argv[1]
    key = sys.argv[2] if len(sys.argv) > 2 else None
    engine = ConversionEngine(api_key=key)
    print(engine.convert(file_path))
