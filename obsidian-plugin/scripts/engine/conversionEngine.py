"""
ConversionEngine — flexible pipeline with independent OCR, AI, and MarkItDown toggles.

Settings model
--------------
enabled_generators : list[str]
    Ordered list of active generator IDs that will be tried as a fallback chain.
    Any subset of: "markitdown", "tesseract", "azure_ocr",
    "azure_document_intelligence", "win_ocr", "gemini"

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
"azure_document_intelligence" — Azure Document Intelligence OCR
                    (requires azure-ai-documentintelligence + key/endpoint)
"win_ocr"     — Windows.Media.Ocr  (Windows 10 1803+, requires winrt package)
"gemini"      — Google Gemini  (requires google-genai + API key)
"""

import base64
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
    from azure.ai.vision.imageanalysis.models import VisualFeatures
    from azure.core.credentials import AzureKeyCredential
    AZURE_OCR_AVAILABLE = True
except ImportError:
    AZURE_OCR_AVAILABLE = False

try:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential as DocumentIntelligenceKeyCredential
    AZURE_DOCUMENT_INTELLIGENCE_AVAILABLE = True
except ImportError:
    AZURE_DOCUMENT_INTELLIGENCE_AVAILABLE = False

WIN_OCR_AVAILABLE = False
WIN_OCR_IMPORT_ERROR: Exception | None = None
if platform.system() == "Windows":
    try:
        import winrt.windows.media.ocr as _win_ocr_mod
        import winrt.windows.graphics.imaging as _win_img
        import winrt.windows.storage.streams as _win_streams
        import asyncio as _asyncio
        WIN_OCR_AVAILABLE = True
    except ImportError as error:
        WIN_OCR_IMPORT_ERROR = error

try:
    import pdf2image as _pdf2image
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False


class _GeminiModelAdapter:
    """Adapt the Google Gen AI client to MarkItDown's LLM client shape.

    Recent MarkItDown releases use the OpenAI-compatible
    ``client.chat.completions.create`` API for image descriptions, while older
    releases used ``generate_content`` directly.  Keep both entry points so
    the plugin remains compatible with either version.
    """

    def __init__(self, engine, system_instruction=None):
        self.engine = engine
        self.system_instruction = system_instruction
        self.chat = _GeminiChat(self)

    def generate_content(self, contents):
        return self.engine._generate_gemini_content(
            contents,
            system_instruction=self.system_instruction,
        )

    def _create_chat_completion(self, model, messages):
        response = self.engine._generate_gemini_content(
            self._messages_to_gemini_contents(messages),
            system_instruction=self.system_instruction,
            model=model,
        )
        return _ChatCompletionResponse(getattr(response, "text", ""))

    @staticmethod
    def _messages_to_gemini_contents(messages):
        """Convert OpenAI-style multimodal messages to Gemini contents."""
        contents = []
        for message in messages:
            parts = []
            raw_content = message.get("content", "")
            items = raw_content if isinstance(raw_content, list) else [{
                "type": "text",
                "text": raw_content,
            }]

            for item in items:
                if item.get("type") == "text":
                    parts.append({"text": item.get("text", "")})
                    continue

                if item.get("type") != "image_url":
                    continue
                image_url = item.get("image_url", {}).get("url", "")
                if image_url.startswith("data:"):
                    header, encoded = image_url.split(",", 1)
                    mime_type = header[5:].split(";", 1)[0] or "application/octet-stream"
                    parts.append({
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64decode(encoded),
                        }
                    })
                elif image_url:
                    parts.append({"file_data": {"file_uri": image_url}})

            if parts:
                contents.append({
                    "role": "model" if message.get("role") == "assistant" else "user",
                    "parts": parts,
                })
        return contents


class _GeminiChat:
    def __init__(self, adapter):
        self.completions = _GeminiChatCompletions(adapter)


class _GeminiChatCompletions:
    def __init__(self, adapter):
        self.adapter = adapter

    def create(self, model, messages, **_kwargs):
        return self.adapter._create_chat_completion(model, messages)


class _ChatCompletionResponse:
    def __init__(self, text):
        self.choices = [
            type(
                "_ChatChoice",
                (),
                {"message": type("_ChatMessage", (), {"content": text})()},
            )()
        ]

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
        Custom system instruction for Gemini. When empty, built-in prompts are
        used for image transcription, ai_improve, and ai_auto_detect.

    azure_ocr_key / azure_ocr_endpoint : str | None
        Azure Computer Vision credentials.

    azure_document_intelligence_key / azure_document_intelligence_endpoint : str | None
        Azure Document Intelligence credentials.

    tesseract_lang : str
        Tesseract language string, e.g. "deu+eng".
    """

    def __init__(
        self,
        enabled_generators: list[str] | None = None,
        ai_improve: bool = False,
        ai_auto_detect: bool = False,
        api_key: str | None = None,
        model_name: str = "gemini-3.1-flash-lite",
        prompt_override: str = "",
        azure_ocr_key: str | None = None,
        azure_ocr_endpoint: str | None = None,
        azure_document_intelligence_key: str | None = None,
        azure_document_intelligence_endpoint: str | None = None,
        tesseract_lang: str = "deu+eng",
        tesseract_cmd: str | None = None,
    ):
        load_dotenv()
        # Preserve an explicitly empty list. It represents a configuration
        # where every generator was disabled; only omitted configuration gets
        # the historical MarkItDown default.
        self.enabled_generators = (
            ["markitdown"] if enabled_generators is None else list(enabled_generators)
        )
        self.ai_improve = ai_improve
        self.ai_auto_detect = ai_auto_detect
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.prompt_override = prompt_override
        self.azure_ocr_key = self._clean_azure_value(
            azure_ocr_key or os.getenv("AZURE_OCR_KEY")
        )
        self.azure_ocr_endpoint = self._clean_azure_value(
            azure_ocr_endpoint or os.getenv("AZURE_OCR_ENDPOINT")
        ).rstrip("/")
        self.azure_document_intelligence_key = self._clean_azure_value(
            azure_document_intelligence_key or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")
        )
        self.azure_document_intelligence_endpoint = self._clean_azure_value(
            azure_document_intelligence_endpoint
            or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
        ).rstrip("/")
        self.tesseract_lang = tesseract_lang
        self.tesseract_cmd = tesseract_cmd

    @staticmethod
    def _clean_azure_value(value: str | None) -> str:
        """Normalize values pasted into the standalone GUI or a .env file."""
        if not value:
            return ""
        return value.strip().strip('"').strip("'").strip()

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

        def analyze(image_data: bytes):
            try:
                return client.analyze(
                    image_data=image_data,
                    visual_features=[VisualFeatures.READ],
                )
            except Exception as error:
                if getattr(error, "status_code", None) == 401:
                    raise RuntimeError(
                        "Azure OCR returned 401 for "
                        f"{self.azure_ocr_endpoint}. The key may be valid but must "
                        "belong to this exact Vision resource, and key-based "
                        "(local) authentication must be enabled."
                    ) from error
                raise

        suffix = Path(file_path).suffix.lower()
        if suffix == ".pdf":
            results = []
            for img in _to_pil_images(file_path):
                import io
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                result = analyze(buf.getvalue())
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
        result = analyze(data)
        if result.read:
            return "\n".join(
                line.text
                for block in result.read.blocks
                for line in block.lines
            )
        return ""

    def _run_azure_document_intelligence(self, file_path: str) -> str:
        """Run Azure Document Intelligence's prebuilt-read model on a file."""
        if not AZURE_DOCUMENT_INTELLIGENCE_AVAILABLE:
            raise RuntimeError("azure-ai-documentintelligence is not installed.")
        if (
            not self.azure_document_intelligence_key
            or not self.azure_document_intelligence_endpoint
        ):
            raise RuntimeError(
                "Azure Document Intelligence key and endpoint must be configured."
            )

        client = DocumentIntelligenceClient(
            endpoint=self.azure_document_intelligence_endpoint,
            credential=DocumentIntelligenceKeyCredential(
                self.azure_document_intelligence_key
            ),
        )
        try:
            with open(file_path, "rb") as file_handle:
                try:
                    poller = client.begin_analyze_document(
                        "prebuilt-read", body=file_handle
                    )
                except TypeError:
                    # Compatibility with SDK versions that still call the input
                    # parameter ``analyze_request``.
                    file_handle.seek(0)
                    poller = client.begin_analyze_document(
                        "prebuilt-read", analyze_request=file_handle
                    )
                result = poller.result()
        except Exception as error:
            if getattr(error, "status_code", None) == 401:
                raise RuntimeError(
                    "Azure Document Intelligence returned 401 for "
                    f"{self.azure_document_intelligence_endpoint}. The key must "
                    "belong to this exact Document Intelligence resource."
                ) from error
            raise
        finally:
            close = getattr(client, "close", None)
            if close:
                close()

        content = getattr(result, "content", None)
        if content:
            return content.strip()

        # Older SDK/API responses may not expose the top-level content field.
        # Reconstruct the same reading order from page lines in that case.
        pages = []
        for page in getattr(result, "pages", None) or []:
            lines = [line.content for line in (getattr(page, "lines", None) or [])]
            if lines:
                pages.append("\n".join(lines))
        return "\n\n---\n\n".join(pages)

    def _run_win_ocr(self, file_path: str) -> str:
        if not WIN_OCR_AVAILABLE:
            detail = ""
            if WIN_OCR_IMPORT_ERROR is not None:
                detail = f" Import failed: {WIN_OCR_IMPORT_ERROR}"
            raise RuntimeError(
                "Windows OCR unavailable. Requires Windows 10 1803+ and the "
                "PyWinRT packages. Install them with: "
                "python -m pip install winrt-Windows.Media.Ocr "
                "winrt-Windows.Foundation "
                "winrt-Windows.Graphics.Imaging "
                "winrt-Windows.Storage.Streams."
                + detail
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
                writer.write_bytes(buf.getvalue())
                await writer.store_async()
                iras.seek(0)
                decoder = await _win_img.BitmapDecoder.create_async(iras)
                soft_bmp = await decoder.get_software_bitmap_async()
                ocr_result = await engine.recognize_async(soft_bmp)
                results.append(ocr_result.text)
            return "\n\n---\n\n".join(results)

        return _asyncio.run(_async_ocr(file_path))

    def _generate_gemini_content(self, contents, system_instruction=None, model=None):
        """Generate content through the current Google Gen AI client API."""
        if not self.api_key:
            raise RuntimeError("No Gemini API key configured.")
        if not GENAI_AVAILABLE:
            raise RuntimeError("google-genai is not installed.")

        client = genai.Client(api_key=self.api_key)
        try:
            requested_model = model or self.model_name
            kwargs = {
                "model": requested_model,
            }
            if system_instruction:
                kwargs["config"] = genai_types.GenerateContentConfig(
                    system_instruction=system_instruction,
                )
            # Use the chat API for requests that may use automatic function
            # calling. The Gen AI SDK recommends Chat.send_message for AFC
            # instead of calling Models.generate_content directly.
            message = self._normalize_chat_message(contents)
            for candidate_model in self._gemini_model_candidates(requested_model):
                kwargs["model"] = candidate_model
                try:
                    chat = client.chats.create(**kwargs)
                    return chat.send_message(message)
                except Exception as error:
                    if not self._is_gemini_unavailable(error):
                        raise
            raise RuntimeError("Gemini models are temporarily unavailable.")
        finally:
            close = getattr(client, "close", None)
            if close:
                close()

    @staticmethod
    def _gemini_model_candidates(requested_model):
        """Return the selected model followed by UI-supported 503 fallbacks."""
        candidates = [
            requested_model,
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
        ]
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _is_gemini_unavailable(error):
        """Only retry a temporary Gemini service-unavailable response."""
        return (
            getattr(error, "code", None) == 503
            or "503 UNAVAILABLE" in str(error).upper()
        )

    @staticmethod
    def _normalize_chat_message(contents):
        """Convert legacy ContentDict/blob input to SDK Part objects."""
        if not isinstance(contents, list):
            return contents

        parts = []
        for item in contents:
            if isinstance(item, dict) and "parts" in item:
                parts.extend(item["parts"])
            elif isinstance(item, dict) and {"mime_type", "data"}.issubset(item):
                parts.append({
                    "inline_data": {
                        "mime_type": item["mime_type"],
                        "data": item["data"],
                    }
                })
            elif isinstance(item, str):
                parts.append({"text": item})
            else:
                parts.append(item)

        normalized = []
        for part in parts:
            if not isinstance(part, dict):
                normalized.append(part)
                continue
            if "text" in part:
                normalized.append(genai_types.Part.from_text(text=part["text"]))
                continue
            inline_data = part.get("inline_data")
            if inline_data:
                normalized.append(genai_types.Part.from_bytes(
                    data=inline_data["data"],
                    mime_type=inline_data["mime_type"],
                ))
                continue
            file_data = part.get("file_data")
            if file_data:
                normalized.append(genai_types.Part.from_uri(
                    file_uri=file_data["file_uri"],
                    mime_type=file_data.get("mime_type"),
                ))
                continue
            normalized.append(part)
        return normalized[0] if len(normalized) == 1 else normalized

    def _run_gemini_direct(self, file_path: str) -> str:
        """Run Gemini directly on the source file, without MarkItDown."""
        import mimetypes

        with open(file_path, "rb") as file:
            file_bytes = file.read()
        mime_type, _ = mimetypes.guess_type(file_path)
        response = self._generate_gemini_content(
            [{"mime_type": mime_type or "application/octet-stream", "data": file_bytes}],
            system_instruction=self.prompt_override or self._default_gemini_image_prompt(),
        )
        return response.text

    @staticmethod
    def _strip_markitdown_description_heading(text: str) -> str:
        """Remove MarkItDown's technical image-description wrapper heading."""
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line.strip().casefold() == "# description:":
                return "\n".join(lines[:index] + lines[index + 1:]).lstrip("\n")
            if line.strip():
                break
        return text

    @staticmethod
    def _default_gemini_image_prompt() -> str:
        """Instruct the vision model to transcribe visible source text only."""
        return (
            "You are a strict image-to-text OCR and Markdown transcription assistant. "
            "Read the image itself and return only the text visibly present in the image, "
            "formatted as clean, well-structured Markdown. "
            "Preserve the original language, wording, names, numbers, punctuation, and meaning. "
            "Convert visual hierarchy into Markdown: use # for the main title and ## for a section heading "
            "only when that hierarchy is clearly visible. If it is not clearly a heading, use **bold** "
            "for the label instead. Use normal paragraphs for body text. Preserve visible labels, lists, "
            "links, bold, italics, quotes, and other formatting using Markdown where supported by the image. "
            "Correct only obvious OCR errors. Do not describe the image, its interface, layout, "
            "colors, icons, or context. Do not summarize, interpret, or translate the text. "
            "Never output AI-analysis labels such as Description, Translation, Content details, "
            "Body Text, Title, Heading, or Overall. Keep a label such as Beschreibung only when it is "
            "actually visible in the image. Do not add titles, labels, explanations, metadata, or invented content. "
            "Output only the final Markdown transcription."
        )

    def _run_gemini_improve(self, text: str) -> str:
        """Post-process extracted text with Gemini to improve quality."""
        if not self.api_key:
            raise RuntimeError("No Gemini API key configured for AI improve.")
        if not GENAI_AVAILABLE:
            raise RuntimeError("google-genai is not installed.")
        system = (
            self.prompt_override
            or (
                "You are a strict OCR cleanup and Markdown formatting assistant. "
                "Return only the clean source text from the input as well-structured Markdown. "
                "Preserve the source language, wording, names, numbers, punctuation, meaning, "
                "and all clearly supported formatting such as headings, paragraphs, lists, "
                "tables, links, bold, italics, quotes, code, and captions. Convert a clearly visible main title "
                "to # and a clearly visible section heading to ##; otherwise use **bold** for the label. "
                "Correct only obvious OCR errors and restore formatting that is supported by the source. "
                "The input may contain an AI-generated image description: discard that meta-description, "
                "summaries, interpretations, translations, and AI-analysis labels such as Description, "
                "Translation, Content details, Body Text, Title, Heading, or Overall. Preserve headings and "
                "labels that are visibly part of the source itself, such as Beschreibung. "
                "Do not add explanations, commentary, metadata, or invented content. "
                "Output only the final Markdown."
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
        valid = {
            "markitdown",
            "tesseract",
            "azure_ocr",
            "azure_document_intelligence",
            "win_ocr",
            "gemini",
        }
        prompt = (
            "Look at the attached file. "
            "Based on its content type, respond with exactly one word — "
            "the best extraction method: markitdown, tesseract, azure_ocr, "
            "azure_document_intelligence, win_ocr, or gemini. "
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
            "azure_document_intelligence": self._run_azure_document_intelligence,
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
                # Never run a method that is not enabled. In particular, AI
                # auto-detect may recommend MarkItDown for a text PDF while
                # the user intentionally selected AI only.
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
