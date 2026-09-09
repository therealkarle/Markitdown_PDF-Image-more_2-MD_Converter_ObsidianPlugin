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


class _FakeModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse("improved markdown")


class _FakeClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.models = _FakeModels()


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
            GenerateContentConfig=_FakeGenerateContentConfig
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
        self.assertEqual(len(client.models.calls), 1)
        call = client.models.calls[0]
        self.assertEqual(call["model"], "test-model")
        self.assertEqual(call["contents"], "raw text")
        self.assertEqual(
            call["config"].system_instruction,
            "Keep the content intact.",
        )


if __name__ == "__main__":
    unittest.main()
