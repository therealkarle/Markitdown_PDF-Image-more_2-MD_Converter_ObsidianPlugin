"""Exercise file selection, the real fallback chain, and the Qt output field."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch


class ConversionFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            import main
        except ModuleNotFoundError as error:
            if error.name == "PySide6":
                raise unittest.SkipTest("Run with the standalone app's Python environment") from error
            raise
        cls.main = main
        cls.app = main.QApplication.instance() or main.QApplication([])

    def setUp(self):
        settings = dict(self.main.DEFAULT_SETTINGS, useOcr=True, useAi=False,
                        ocrPriority=["tesseract"])
        with patch.object(self.main.MarkItDownApp, "_load_settings", return_value=settings), \
             patch.object(self.main.MarkItDownApp, "_load_separate_flag", return_value=False):
            self.window = self.main.MarkItDownApp()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_start_button_converts_selected_image_after_empty_markitdown(self):
        file_path = str(Path(__file__).parents[1] / "Testfiles" / "firefox_rSX6oGI9gX.png")
        with patch.object(self.main.QFileDialog, "getOpenFileName", return_value=(file_path, "")):
            self.window._on_select_file()
        self.assertTrue(self.window.start_conversion_btn.isEnabled())
        self.window._on_start_conversion()
        output = self.window.output_text.toPlainText()
        self.assertIn("Beschreibung", output)
        self.assertNotIn("Error:", output)
        self.assertEqual(self.window.session_file.last_file_path, file_path)

    def test_ai_remains_a_fallback_when_auto_detect_is_enabled(self):
        settings = dict(
            self.main.DEFAULT_SETTINGS,
            useMarkitdown=False,
            useAi=True,
            aiAutoDetect=True,
        )
        self.assertEqual(self.main._build_enabled_generators(settings), ["gemini"])

    def test_selecting_file_does_not_start_conversion_automatically(self):
        file_path = str(Path(__file__).parents[1] / "Testfiles" / "firefox_rSX6oGI9gX.png")
        with patch.object(self.main.QFileDialog, "getOpenFileName", return_value=(file_path, "")), \
             patch.object(self.main.ConversionEngine, "convert") as convert:
            self.window._on_select_file()
        convert.assert_not_called()
        self.assertEqual(self.window.output_text.toPlainText(), "")

    def test_start_without_file_shows_actionable_message(self):
        self.window._on_start_conversion()
        self.assertIn("Select a file", self.window.output_text.toPlainText())

    def test_empty_results_show_an_error_instead_of_the_placeholder(self):
        with patch.object(self.main.ConversionEngine, "convert", return_value=" \n\t"):
            self.window._convert("empty.png")
        self.assertIn("No text extracted", self.window.output_text.toPlainText())

    def test_engine_initialization_failure_is_displayed(self):
        with patch.object(self.main, "ConversionEngine", side_effect=RuntimeError("Setup failed")):
            self.window._convert("input.png")
        self.assertIn("Setup failed", self.window.output_text.toPlainText())

    def test_output_is_displayed_as_literal_text(self):
        with patch.object(self.main.ConversionEngine, "convert", return_value="<div>OCR text</div>"):
            self.window._convert("input.png")
        self.assertEqual(self.window.output_text.toPlainText(), "<div>OCR text</div>")


if __name__ == "__main__":
    unittest.main()
