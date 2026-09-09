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
    module_name = "tesseract_resolution_test_engine"
    spec = importlib.util.spec_from_file_location(module_name, ENGINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "markitdown", markitdown)
        patch.setitem(sys.modules, "dotenv", dotenv)
        spec.loader.exec_module(module)
    return module


def test_resolves_windows_installation_outside_path(tmp_path, monkeypatch) -> None:
    module = _load_engine_module()
    install_dir = tmp_path / "Tesseract-OCR"
    install_dir.mkdir()
    executable = install_dir / "tesseract.exe"
    executable.write_bytes(b"test")

    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert module._resolve_tesseract_command() == str(executable.resolve())


def test_reports_actionable_error_when_tesseract_is_missing(monkeypatch) -> None:
    module = _load_engine_module()
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with pytest.raises(RuntimeError, match="TESSERACT_CMD"):
        module._resolve_tesseract_command()


def test_runs_native_tesseract_without_pytesseract() -> None:
    image_path = Path(__file__).parents[1] / "Testfiles" / "firefox_rSX6oGI9gX.png"
    if not image_path.exists():
        pytest.skip("OCR fixture is not available")

    module = _load_engine_module()
    engine = module.ConversionEngine(
        enabled_generators=["tesseract"],
        tesseract_lang="deu+eng",
    )
    result = engine._run_tesseract(str(image_path))

    assert result.strip()


@pytest.mark.parametrize("empty_result", ["", " \n\t", None])
def test_empty_native_extraction_continues_to_ocr(monkeypatch, empty_result):
    module = _load_engine_module()
    engine = module.ConversionEngine(enabled_generators=["markitdown", "tesseract"])
    calls = []

    def run_generator(generator, _path):
        calls.append(generator)
        return empty_result if generator == "markitdown" else "Recognized text"

    monkeypatch.setattr(engine, "_run_generator", run_generator)
    assert engine.convert("image.png") == "Recognized text"
    assert calls == ["markitdown", "tesseract"]


def test_all_empty_generators_report_failure(monkeypatch):
    module = _load_engine_module()
    engine = module.ConversionEngine(enabled_generators=["markitdown", "tesseract"])
    monkeypatch.setattr(engine, "_run_generator", lambda *_args: " \n")
    result = engine.convert("blank.png")
    assert result.startswith("Error:")
    assert "markitdown: No text extracted" in result
    assert "tesseract: No text extracted" in result


def test_empty_ai_improvement_preserves_extracted_text(monkeypatch):
    module = _load_engine_module()
    engine = module.ConversionEngine(enabled_generators=["tesseract"], ai_improve=True)
    monkeypatch.setattr(engine, "_run_generator", lambda *_args: "Recognized text")
    monkeypatch.setattr(engine, "_run_gemini_improve", lambda _text: "")
    assert engine.convert("image.png") == "Recognized text"
