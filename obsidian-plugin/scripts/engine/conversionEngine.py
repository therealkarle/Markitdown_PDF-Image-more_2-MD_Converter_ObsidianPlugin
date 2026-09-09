"""
ConversionEngine — flexible pipeline with independent OCR, AI, and MarkItDown toggles.

Settings model
--------------
enabled_generators : list[str]
    Ordered list of active generator IDs that will be tried as a fallback chain.
    Any subset of: "markitdown", "tesseract", "azure_ocr", "win_ocr", "gemini"

ai_improve : bool
    When True and "gemini" is in enabled_generators, Gemini runs as an *additional*
    post-processing pass after the first successful generator to improve the result.
    When False, Gemini is just another entry in the fallback chain.

ai_auto_detect : bool
    When True, Gemini inspects the file first and decides which generator to use,
    then runs that generator (and still applies ai_improve if enabled).

Generator IDs
-------------
"markitdown"  — MarkItDown native (best for PDF, Word, HTML, …)
"tesseract"   — Tesseract OCR  (requires the native system binary)
"azure_ocr"   — Azure Computer Vision  (requires azure-ai-vision-imageanalysis + key/endpoint)
"win_ocr"     — Windows.Media.Ocr  (Windows 10 1803+, requires winrt package)
"gemini"      — Google Gemini  (requires google-genai + API key)
"""

import os
import shutil
import subprocess
import sys
import tempfile
import platform
from pathlib import Path
from markitdown import MarkItDown
from dotenv import load_dotenv

# ── Optional dependency guards ────────────────────────────────────────────────

try:
    from google import genai
    from google.genai import types as genai_types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

try:
    from azure.ai.vision.imageanalysis import ImageAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    AZURE_OCR_AVAILABLE = True
except ImportError:
    AZURE_OCR_AVAILABLE = False

WIN_OCR_AVAILABLE = False
if platform.system() == "Windows":
    try:
        import winrt.windows.media.ocr as _win_ocr_mod
        import winrt.windows.globalization as _win_glob
        import winrt.windows.graphics.imaging as _win_img
        import winrt.windows.storage.streams as _win_streams
        import asyncio as _asyncio
        WIN_OCR_AVAILABLE = True
    except ImportError:
        pass

try:
    import pdf2image as _pdf2image
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False


class _GeminiModelAdapter:
    """Expose the legacy ``generate_content`` shape used by MarkItDown."""

    def __init__(self, engine, system_instruction=None):
        self.engine = engine
        self.system_instruction = system_instruction

    def generate_content(self, contents):
        return self.engine._generate_gemini_content(
            contents,
            system_instruction=self.system_instruction,
        )

# ── Image helpers ─────────────────────────────────────────────────────────────

def _to_pil_images(file_path: str) -> list:
    """Return a list of PIL Images from a PDF or image file."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        if not PDF2IMAGE_AVAILABLE:
            raise RuntimeError(
                "pdf2image is not installed. Run: pip install pdf2image"
            )
        return _pdf2image.convert_from_path(file_path)
    from PIL import Image as PILImage
    return [PILImage.open(file_path)]


def _resolve_tesseract_command(configured_command: str | None = None) -> str:
    """Find the Tesseract executable even when the host process has no PATH entry."""
    configured = configured_command or os.getenv("TESSERACT_CMD")
    candidates: list[Path] = []

    if configured:
        configured_path = Path(os.path.expandvars(configured)).expanduser()
        candidates.append(
            configured_path / "tesseract.exe"
            if configured_path.is_dir()
            else configured_path
        )

    from_path = shutil.which("tesseract")
    if from_path:
        candidates.append(Path(from_path))

    for root_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.getenv(root_name)
        if root:
            candidates.append(Path(root) / "Tesseract-OCR" / "tesseract.exe")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())

    searched = ", ".join(str(candidate) for candidate in candidates) or "PATH"
    raise RuntimeError(
        "Tesseract executable not found. Install Tesseract or set TESSERACT_CMD "
        f"to the tesseract.exe path (searched: {searched})."
    )


# ── Engine ────────────────────────────────────────────────────────────────────

class ConversionEngine:
    """
    Parameters
    ----------
    enabled_generators : list[str]
        Ordered fallback chain of generator IDs.
        Example: ["markitdown", "tesseract", "gemini"]

    ai_improve : bool
        Post-process the first successful result with Gemini (even if Gemini
        is not in enabled_generators, or is further back in the chain).

    ai_auto_detect : bool
        Let Gemini inspect the file and pick the best generator before running
        the normal chain.

    api_key : str | None
        Gemini API key (falls back to GEMINI_API_KEY env var).

    model_name : str
        Gemini model to use.

    prompt_override : str
        Custom system instruction for Gemini.  When empty the built-in
        improvement prompt is used for ai_improve, and a detection prompt for
        ai_auto_detect.

    azure_ocr_key / azure_ocr_endpoint : str | None
        Azure Computer Vision credentials.

    tesseract_lang : str
        Tesseract language string, e.g. "deu+eng".
    """

    def __init__(
        self,
        enabled_generators: list[str] | None = None,
        ai_improve: bool = False,
        ai_auto_detect: bool = False,
        api_key: str | None = None,
        model_name: str = "gemini-2.0-flash-lite-preview-02-05",
        prompt_override: str = "",
        azure_ocr_key: str | None = None,
        azure_ocr_endpoint: str | None = None,
        tesseract_lang: str = "deu+eng",
        tesseract_cmd: str | None = None,
    ):
        load_dotenv()
        self.enabled_generators = enabled_generators or ["markitdown"]
        self.ai_improve = ai_improve
        self.ai_auto_detect = ai_auto_detect
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.prompt_override = prompt_override
        self.azure_ocr_key = azure_ocr_key or os.getenv("AZURE_OCR_KEY")
        self.azure_ocr_endpoint = azure_ocr_endpoint or os.getenv("AZURE_OCR_ENDPOINT")
        self.tesseract_lang = tesseract_lang
        self.tesseract_cmd = tesseract_cmd

    # ── Individual generators ─────────────────────────────────────────────────

    def _run_markitdown(self, file_path: str) -> str:
        return MarkItDown().convert(file_path).text_content

    def _run_tesseract(self, file_path: str) -> str:
        command = _resolve_tesseract_command(self.tesseract_cmd)
        try:
            language_output = subprocess.run(
                [command, "--list-langs"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            ).stdout
        except Exception as error:
            raise RuntimeError(
                f"Tesseract could not be started at '{command}': {error}"
            ) from error

        available_languages = {
            line.strip()
            for line in language_output.splitlines()
            if line.strip() and not line.startswith("List of available languages")
        }
        requested_languages = [
            language.strip()
            for language in self.tesseract_lang.replace(",", "+").split("+")
            if language.strip()
        ]
        missing_languages = [
            language
            for language in requested_languages
            if language not in available_languages
        ]
        if missing_languages:
            available = ", ".join(sorted(available_languages))
            raise RuntimeError(
                "Tesseract language data not found: "
                f"{', '.join(missing_languages)}. Available languages: {available}"
            )

        try:
            suffix = Path(file_path).suffix.lower()
            if suffix != ".pdf":
                pages = [self._run_tesseract_cli(command, file_path)]
            else:
                images = _to_pil_images(file_path)
                with tempfile.TemporaryDirectory(prefix="markitdown-ocr-") as temp_dir:
                    pages = []
                    for index, image in enumerate(images, start=1):
                        image_path = Path(temp_dir) / f"page-{index}.png"
                        image.save(image_path, format="PNG")
                        pages.append(self._run_tesseract_cli(command, str(image_path)))
        except Exception as error:
            raise RuntimeError(f"Tesseract OCR failed: {error}") from error
        return "\n\n---\n\n".join(pages)

    def _run_tesseract_cli(self, command: str, file_path: str) -> str:
        """Run the native Tesseract CLI without requiring pytesseract."""
        result = subprocess.run(
            [command, file_path, "stdout", "-l", self.tesseract_lang],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout).strip()
            raise RuntimeError(details or f"process exited with code {result.returncode}")
        return result.stdout.strip()

    def _run_azure_ocr(self, file_path: str) -> str:
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
            results = []
            for img in _to_pil_images(file_path):
                import io
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                result = client.analyze(
                    image_data=buf.getvalue(),
                    visual_features=["READ"],
                )
                if result.read:
                    results.append(
                        "\n".join(
                            line.text
                            for block in result.read.blocks
                            for line in block.lines
                        )
                    )
            return "\n\n---\n\n".join(results)
        with open(file_path, "rb") as f:
            data = f.read()
        result = client.analyze(image_data=data, visual_features=["READ"])
        if result.read:
            return "\n".join(
                line.text
                for block in result.read.blocks
                for line in block.lines
            )
        return ""

    def _run_win_ocr(self, file_path: str) -> str:
        if not WIN_OCR_AVAILABLE:
            raise RuntimeError(
                "Windows OCR unavailable. Requires Windows 10 1803+ and the winrt package."
            )

        async def _async_ocr(path: str) -> str:
            images = _to_pil_images(path)
            results = []
            engine = _win_ocr_mod.OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                raise RuntimeError("Could not create Windows OCR engine.")
            for pil_img in images:
                import io
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                buf.seek(0)
                iras = _win_streams.InMemoryRandomAccessStream()
                writer = _win_streams.DataWriter(iras)
                writer.write_bytes(list(buf.getvalue()))
                await writer.store_async()
                iras.seek(0)
                decoder = await _win_img.BitmapDecoder.create_async(iras)
                soft_bmp = await decoder.get_software_bitmap_async()
                ocr_result = await engine.recognize_async(soft_bmp)
                results.append(ocr_result.text)
            return "\n\n---\n\n".join(results)

        return _asyncio.run(_async_ocr(file_path))

    def _generate_gemini_content(self, contents, system_instruction=None):
        """Generate content through the current Google Gen AI client API."""
        if not self.api_key:
            raise RuntimeError("No Gemini API key configured.")
        if not GENAI_AVAILABLE:
            raise RuntimeError("google-genai is not installed.")

        client = genai.Client(api_key=self.api_key)
        try:
            kwargs = {
                "model": self.model_name,
                "contents": contents,
            }
            if system_instruction:
                kwargs["config"] = genai_types.GenerateContentConfig(
                    system_instruction=system_instruction,
                )
            return client.models.generate_content(**kwargs)
        finally:
            close = getattr(client, "close", None)
            if close:
                close()

    def _run_gemini_direct(self, file_path: str) -> str:
        """Run Gemini directly on the file (used as a generator in the chain)."""
        model = _GeminiModelAdapter(
            self,
            system_instruction=self.prompt_override or None,
        )
        md = MarkItDown(llm_client=model, llm_model=self.model_name)
        return md.convert(file_path).text_content

    def _run_gemini_improve(self, text: str) -> str:
        """Post-process extracted text with Gemini to improve quality."""
        if not self.api_key:
            raise RuntimeError("No Gemini API key configured for AI improve.")
        if not GENAI_AVAILABLE:
            raise RuntimeError("google-genai is not installed.")
        system = (
            self.prompt_override
            or (
                "You are a document formatting assistant. "
                "Clean up and improve the following extracted text into well-structured Markdown. "
                "Fix OCR errors, restore formatting, keep all content intact. "
                "Return only the improved Markdown, no commentary."
            )
        )
        response = self._generate_gemini_content(
            text,
            system_instruction=system,
        )
        return response.text

    def _run_gemini_auto_detect(self, file_path: str) -> str:
        """
        Ask Gemini to inspect the file and decide which extraction method fits best,
        then return that generator ID so we can re-run the appropriate chain.
        Falls back to the normal chain if detection fails.
        """
        if not self.api_key:
            raise RuntimeError("No Gemini API key configured for AI auto-detect.")
        if not GENAI_AVAILABLE:
            raise RuntimeError("google-genai is not installed.")
        valid = {"markitdown", "tesseract", "azure_ocr", "win_ocr", "gemini"}
        prompt = (
            "Look at the attached file. "
            "Based on its content type, respond with exactly one word — "
            "the best extraction method: markitdown, tesseract, azure_ocr, win_ocr, or gemini. "
            "Respond with only the method name, nothing else."
        )
        try:
            # Upload / inline the file for inspection
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            import mimetypes
            mime, _ = mimetypes.guess_type(file_path)
            mime = mime or "application/octet-stream"
            response = self._generate_gemini_content([
                {"mime_type": mime, "data": file_bytes},
                prompt,
            ])
            detected = response.text.strip().lower()
            if detected in valid:
                return detected
        except Exception:
            pass
        return None  # Caller falls through to normal chain

    # ── Main dispatch ─────────────────────────────────────────────────────────

    def _run_generator(self, gen_id: str, file_path: str) -> str:
        dispatch = {
            "markitdown": self._run_markitdown,
            "tesseract": self._run_tesseract,
            "azure_ocr": self._run_azure_ocr,
            "win_ocr": self._run_win_ocr,
            "gemini": self._run_gemini_direct,
        }
        fn = dispatch.get(gen_id)
        if fn is None:
            raise RuntimeError(f"Unknown generator: {gen_id!r}")
        return fn(file_path)

    def convert(self, file_path: str) -> str:
        """
        Convert *file_path* to Markdown.

        Pipeline:
        1. If ai_auto_detect → ask Gemini which generator fits best.
           Reorder enabled_generators so that generator comes first.
        2. Walk enabled_generators as a fallback chain until one succeeds.
        3. If ai_improve → send the successful result through Gemini for cleanup.
        """
        errors: list[str] = []
        chain = list(self.enabled_generators)

        # Step 1 — AI auto-detect (optional reorder)
        if self.ai_auto_detect:
            try:
                detected = self._run_gemini_auto_detect(file_path)
                if detected and detected in chain:
                    # Move detected generator to the front
                    chain = [detected] + [g for g in chain if g != detected]
                elif detected and detected not in chain:
                    # Detected method is not enabled — prepend it anyway
                    chain = [detected] + chain
            except Exception as e:
                errors.append(f"ai_auto_detect: {e}")

        # Step 2 — Fallback chain
        base_result: str | None = None
        for gen_id in chain:
            try:
                result = self._run_generator(gen_id, file_path)
                if not result or not result.strip():
                    errors.append(f"{gen_id}: No text extracted.")
                    continue
                base_result = result
                break
            except Exception as e:
                errors.append(f"{gen_id}: {e}")

        if base_result is None:
            return "Error: All generators failed. " + " | ".join(errors)

        # Step 3 — AI improve (optional post-process)
        if self.ai_improve:
            try:
                improved_result = self._run_gemini_improve(base_result)
                if improved_result and improved_result.strip():
                    return improved_result
            except Exception as e:
                errors.append(f"ai_improve: {e}")
                # Return base result if improvement fails

        return base_result


# ── CLI entry point ───────────────────────────────────────────────────────────
# python -m engine.conversionEngine <file_path> [api_key]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m engine.conversionEngine <file_path> [api_key]")
        sys.exit(1)

    engine = ConversionEngine(
        enabled_generators=["markitdown"],
        api_key=sys.argv[2] if len(sys.argv) > 2 else None,
    )
    print(engine.convert(sys.argv[1]))
