from pathlib import Path


SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")


def test_standalone_main_is_valid_python() -> None:
    compile(SOURCE, "standalone-app/main.py", "exec")


def _settings_ui_source() -> str:
    start = SOURCE.index("    def _build_settings_tab")
    end = SOURCE.index("    def _populate_block_list", start)
    return SOURCE[start:end]


def test_azure_key_is_requested_inside_the_ocr_section() -> None:
    settings_ui = _settings_ui_source()
    ocr_start = settings_ui.index("2. OCR sub-options")
    ai_start = settings_ui.index("3. AI sub-options")
    ocr_source = settings_ui[ocr_start:ai_start]

    assert "self.azure_key_input = QLineEdit" in ocr_source
    assert 'ocr_form.addRow("Azure Computer Vision key:", self.azure_key_input)' in ocr_source
    assert 'ocr_form.addRow("Azure Computer Vision endpoint:", self.azure_endpoint_input)' in ocr_source
    assert "self.azure_di_key_input = QLineEdit" in ocr_source


def test_standalone_settings_has_no_separate_azure_credentials_section() -> None:
    settings_ui = _settings_ui_source()

    assert "cred_group = QGroupBox" not in settings_ui


def test_standalone_settings_use_scrollable_content() -> None:
    settings_ui = _settings_ui_source()

    assert "settings_scroll = QScrollArea()" in settings_ui
    assert "settings_scroll.setWidgetResizable(True)" in settings_ui
    assert "settings_scroll.setWidget(settings_content)" in settings_ui


def test_ocr_subengines_are_shown_without_an_inner_scrollbar() -> None:
    settings_ui = _settings_ui_source()

    assert "self.ocr_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)" in settings_ui
    assert "self._fit_ocr_list_height()" in SOURCE
    assert "def _fit_ocr_list_height" in SOURCE
    assert "row_height = self.ocr_list.sizeHintForRow(0)" in SOURCE
