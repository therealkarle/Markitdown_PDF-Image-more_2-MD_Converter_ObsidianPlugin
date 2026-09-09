import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).parents[1] / "obsidian-plugin" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))


spec = importlib.util.spec_from_file_location("obsidian_convert", SCRIPT_DIR / "convert.py")
convert_script = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(convert_script)


def test_engine_error_is_raised_instead_of_being_returned_as_markdown(monkeypatch) -> None:
    class FakeEngine:
        def __init__(self, **_kwargs):
            pass

        def convert(self, _file_path):
            return "Error: All generators failed. markitdown: input unreadable"

    monkeypatch.setattr(convert_script, "ConversionEngine", FakeEngine)

    with pytest.raises(RuntimeError, match="All generators failed"):
        convert_script.convert_file("input.pdf", {})
