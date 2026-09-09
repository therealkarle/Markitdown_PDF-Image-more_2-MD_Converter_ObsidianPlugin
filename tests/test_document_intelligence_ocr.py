import importlib.util
import sys
import types
from pathlib import Path


ENGINE_PATH = Path(__file__).parents[1] / "engine" / "conversionEngine.py"


def _load_engine_module():
    markitdown = types.ModuleType("markitdown")
    markitdown.MarkItDown = object
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None
    module_name = "document_intelligence_test_engine"
    spec = importlib.util.spec_from_file_location(module_name, ENGINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with __import__("pytest").MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "markitdown", markitdown)
        patch.setitem(sys.modules, "dotenv", dotenv)
        spec.loader.exec_module(module)
    return module


def test_document_intelligence_returns_analyzed_content(monkeypatch, tmp_path) -> None:
    module = _load_engine_module()
    calls = {}

    class FakeCredential:
        def __init__(self, key):
            calls["key"] = key

    class FakePoller:
        def result(self):
            return types.SimpleNamespace(content="Recognized document text")

    class FakeClient:
        def __init__(self, endpoint, credential):
            calls["endpoint"] = endpoint
            calls["credential"] = credential

        def begin_analyze_document(self, model_id, body):
            calls["model_id"] = model_id
            calls["body"] = body.read()
            return FakePoller()

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(module, "AZURE_DOCUMENT_INTELLIGENCE_AVAILABLE", True)
    monkeypatch.setattr(module, "DocumentIntelligenceClient", FakeClient)
    monkeypatch.setattr(module, "DocumentIntelligenceKeyCredential", FakeCredential)

    input_path = tmp_path / "document.pdf"
    input_path.write_bytes(b"pdf-bytes")
    engine = module.ConversionEngine(
        enabled_generators=["azure_document_intelligence"],
        azure_document_intelligence_key="di-key",
        azure_document_intelligence_endpoint="https://di.example",
    )

    assert engine.convert(str(input_path)) == "Recognized document text"
    assert calls == {
        "key": "di-key",
        "endpoint": "https://di.example",
        "credential": calls["credential"],
        "model_id": "prebuilt-read",
        "body": b"pdf-bytes",
        "closed": True,
    }


def test_document_intelligence_requires_its_own_credentials(monkeypatch) -> None:
    module = _load_engine_module()
    monkeypatch.setattr(module, "AZURE_DOCUMENT_INTELLIGENCE_AVAILABLE", True)
    engine = module.ConversionEngine(enabled_generators=["azure_document_intelligence"])

    with __import__("pytest").raises(
        RuntimeError, match="Azure Document Intelligence key and endpoint"
    ):
        engine._run_azure_document_intelligence("document.pdf")
