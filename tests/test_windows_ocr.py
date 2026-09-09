import importlib.util
import sys
import types
from pathlib import Path

import pytest


ENGINE_PATH = Path(__file__).parents[1] / "engine" / "conversionEngine.py"


def _load_engine_module():
    markitdown = types.ModuleType("markitdown")
    markitdown.MarkItDown = object
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None
    module_name = "windows_ocr_test_engine"
    spec = importlib.util.spec_from_file_location(module_name, ENGINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "markitdown", markitdown)
        patch.setitem(sys.modules, "dotenv", dotenv)
        spec.loader.exec_module(module)
    return module


def test_missing_windows_ocr_dependency_has_install_hint(monkeypatch) -> None:
    module = _load_engine_module()
    engine = module.ConversionEngine(enabled_generators=["win_ocr"])
    monkeypatch.setattr(module, "WIN_OCR_AVAILABLE", False)
    monkeypatch.setattr(
        module,
        "WIN_OCR_IMPORT_ERROR",
        ModuleNotFoundError("No module named 'winrt'")
    )

    with pytest.raises(RuntimeError, match="winrt-Windows.Media.Ocr"):
        engine._run_win_ocr("image.png")


def test_windows_ocr_writes_binary_image_data(monkeypatch) -> None:
    module = _load_engine_module()
    written_values = []

    class FakeImage:
        def save(self, stream, format):
            assert format == "PNG"
            stream.write(b"png-bytes")

    class FakeStream:
        def seek(self, position):
            assert position == 0

    class FakeWriter:
        def __init__(self, _stream):
            pass

        def write_bytes(self, value):
            written_values.append(value)

        async def store_async(self):
            return None

    class FakeDecoder:
        @staticmethod
        async def create_async(_stream):
            return FakeDecoder()

        async def get_software_bitmap_async(self):
            return object()

    class FakeOcrEngine:
        @staticmethod
        def try_create_from_user_profile_languages():
            return FakeOcrEngine()

        async def recognize_async(self, _bitmap):
            return types.SimpleNamespace(text="Recognized text")

    monkeypatch.setattr(module, "WIN_OCR_AVAILABLE", True)
    monkeypatch.setattr(module, "_to_pil_images", lambda _path: [FakeImage()])
    monkeypatch.setattr(
        module,
        "_win_streams",
        types.SimpleNamespace(
            InMemoryRandomAccessStream=FakeStream,
            DataWriter=FakeWriter,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "_win_img",
        types.SimpleNamespace(BitmapDecoder=FakeDecoder),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "_win_ocr_mod",
        types.SimpleNamespace(OcrEngine=FakeOcrEngine),
        raising=False,
    )
    monkeypatch.setattr(module, "_asyncio", __import__("asyncio"), raising=False)

    engine = module.ConversionEngine(enabled_generators=["win_ocr"])
    assert engine._run_win_ocr("image.png") == "Recognized text"
    assert written_values == [b"png-bytes"]
