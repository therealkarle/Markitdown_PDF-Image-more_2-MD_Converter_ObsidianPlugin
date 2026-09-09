import sys
import types
import unittest
from importlib import import_module
from unittest.mock import patch


class _FakeMarkItDown:
    def __init__(self, *args, **kwargs):
        pass


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _AdapterEngine:
    def __init__(self):
        self.calls = []

    def _generate_gemini_content(self, contents, system_instruction=None, model=None):
        self.calls.append(
            {
                "contents": contents,
                "system_instruction": system_instruction,
                "model": model,
            }
        )
        return _FakeResponse("image description")


class _FakeChat:
    def __init__(self):
        self.create_kwargs = None
        self.calls = []

    def send_message(self, contents):
        self.calls.append(contents)
        return _FakeResponse("improved markdown")


class _FakeClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.chats = self
        self.chat = _FakeChat()

    def create(self, **kwargs):
        self.chat.create_kwargs = kwargs
        return self.chat


class _FakeGenai:
    def __init__(self):
        self.clients = []

    def Client(self, api_key):
        client = _FakeClient(api_key)
        self.clients.append(client)
        return client


class _FakeGenerateContentConfig:
    def __init__(self, system_instruction=None):
        self.system_instruction = system_instruction


class _FakePart:
    @classmethod
    def from_text(cls, *, text):
        return {"text": text}

    @classmethod
    def from_bytes(cls, *, data, mime_type):
        return {"inline_data": {"mime_type": mime_type, "data": data}}

    @classmethod
    def from_uri(cls, *, file_uri, mime_type=None):
        return {"file_data": {"file_uri": file_uri, "mime_type": mime_type}}


class GeminiMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        markitdown = types.ModuleType("markitdown")
        markitdown.MarkItDown = _FakeMarkItDown
        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda: None
        cls._module_patches = patch.dict(
            sys.modules,
            {"markitdown": markitdown, "dotenv": dotenv},
        )
        cls._module_patches.start()
        cls.module = import_module("engine.conversionEngine")

    @classmethod
    def tearDownClass(cls):
        cls._module_patches.stop()

    def test_improve_uses_new_google_genai_client_api(self):
        fake_genai = _FakeGenai()
        fake_types = types.SimpleNamespace(
            GenerateContentConfig=_FakeGenerateContentConfig,
            Part=_FakePart,
        )
        with patch.object(self.module, "genai", fake_genai, create=True), patch.object(
            self.module, "genai_types", fake_types, create=True
        ), patch.object(self.module, "GENAI_AVAILABLE", True):
            engine = self.module.ConversionEngine(
                api_key="test-key",
                model_name="test-model",
                prompt_override="Keep the content intact.",
            )

            result = engine._run_gemini_improve("raw text")

        self.assertEqual(result, "improved markdown")
        self.assertEqual(len(fake_genai.clients), 1)
        client = fake_genai.clients[0]
        self.assertEqual(client.api_key, "test-key")
        self.assertEqual(len(client.chat.calls), 1)
        call = client.chat.create_kwargs
        self.assertEqual(call["model"], "test-model")
        self.assertEqual(
            call["config"].system_instruction,
            "Keep the content intact.",
        )
        self.assertEqual(client.chat.calls[0], "raw text")

    def test_default_improve_prompt_returns_only_source_markdown(self):
        fake_genai = _FakeGenai()
        fake_types = types.SimpleNamespace(
            GenerateContentConfig=_FakeGenerateContentConfig,
            Part=_FakePart,
        )
        with patch.object(self.module, "genai", fake_genai, create=True), patch.object(
            self.module, "genai_types", fake_types, create=True
        ), patch.object(self.module, "GENAI_AVAILABLE", True):
            engine = self.module.ConversionEngine(
                api_key="test-key",
                model_name="test-model",
            )
            engine._run_gemini_improve("AI image description")

        prompt = fake_genai.clients[0].chat.create_kwargs["config"].system_instruction
        self.assertIn("Return only the clean source text", prompt)
        self.assertIn("discard that meta-description", prompt)
        self.assertIn("translations", prompt)
        self.assertIn("Preserve headings and labels", prompt)

    def test_default_direct_prompt_is_transcription_only(self):
        prompt = self.module.ConversionEngine._default_gemini_image_prompt()
        self.assertIn("Read the image itself", prompt)
        self.assertIn("return only the text visibly present", prompt)
        self.assertIn("Do not describe the image", prompt)
        self.assertIn("Do not summarize, interpret, or translate", prompt)

    def test_gemini_503_uses_ui_supported_model_fallbacks(self):
        engine = self.module.ConversionEngine(model_name="gemini-3.1-flash-lite")

        self.assertEqual(
            engine._gemini_model_candidates(engine.model_name),
            [
                "gemini-3.1-flash-lite",
                "gemini-3.5-flash-lite",
                "gemini-3.8-flash",
                "gemini-3.7-flash",
            ],
        )

        unavailable = RuntimeError("503 UNAVAILABLE")
        self.assertTrue(engine._is_gemini_unavailable(unavailable))
        self.assertFalse(engine._is_gemini_unavailable(RuntimeError("401 UNAUTHORIZED")))

    def test_markitdown_chat_completion_adapter_converts_image_messages(self):
        engine = _AdapterEngine()
        adapter = self.module._GeminiModelAdapter(
            engine,
            system_instruction="Describe the image.",
        )

        result = adapter.chat.completions.create(
            model="test-model",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Write a caption."},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,AAE="},
                        },
                    ],
                }
            ],
        )

        self.assertEqual(result.choices[0].message.content, "image description")
        self.assertEqual(len(engine.calls), 1)
        call = engine.calls[0]
        self.assertEqual(call["model"], "test-model")
        self.assertEqual(call["system_instruction"], "Describe the image.")
        self.assertEqual(call["contents"][0]["role"], "user")
        self.assertEqual(call["contents"][0]["parts"][0], {"text": "Write a caption."})
        self.assertEqual(
            call["contents"][0]["parts"][1],
            {"inline_data": {"mime_type": "image/png", "data": b"\x00\x01"}},
        )

    def test_chat_api_normalizes_content_dicts_to_parts(self):
        fake_genai = _FakeGenai()
        fake_types = types.SimpleNamespace(
            GenerateContentConfig=_FakeGenerateContentConfig,
            Part=_FakePart,
        )
        with patch.object(self.module, "genai", fake_genai, create=True), patch.object(
            self.module, "genai_types", fake_types, create=True
        ), patch.object(self.module, "GENAI_AVAILABLE", True):
            engine = self.module.ConversionEngine(
                api_key="test-key",
                model_name="test-model",
            )
            engine._generate_gemini_content([
                {
                    "role": "user",
                    "parts": [
                        {"text": "Describe the image."},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": b"\x00\x01",
                            }
                        },
                    ],
                }
            ])

        self.assertEqual(
            fake_genai.clients[0].chat.calls[0],
            [
                {"text": "Describe the image."},
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": b"\x00\x01",
                    }
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
