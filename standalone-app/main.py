import json
import os
import platform
import sys
from pathlib import Path

# Add the repo root to sys.path so the shared engine package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv, set_key
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QTextEdit,
    QVBoxLayout, QWidget, QTabWidget,
)
from engine.conversionEngine import ConversionEngine

# ─── Mode / option definitions ───────────────────────────────────────────────

MODE_LABELS = ["Simple (MarkItDown native)", "OCR", "AI Enhanced"]
MODE_VALUES = ["simple", "ocr", "ai_enhanced"]

AI_MODE_LABELS = [
    "Fallback  (AI only when all others fail)",
    "Enhancement  (AI improves every result)",
]
AI_MODE_VALUES = ["fallback", "enhancement"]

# OCR engines, platform-aware
_OCR_OPTIONS: list[tuple[str, str]] = [
    ("tesseract", "Tesseract  (local)"),
    ("azure_ocr", "Azure Computer Vision  (cloud)"),
]
if platform.system() == "Windows":
    _OCR_OPTIONS.append(("win_ocr", "Windows OCR  (local, Windows only)"))

OCR_ENGINE_IDS = [eid for eid, _ in _OCR_OPTIONS]
OCR_ENGINE_LABELS = {eid: label for eid, label in _OCR_OPTIONS}

DEFAULT_SETTINGS: dict = {
    # conversion mode
    "mode": "simple",
    # AI settings
    "geminiApiKey": "",
    "modelName": "gemini-2.0-flash-lite-preview-02-05",
    "promptOverride": "",
    "aiMode": "fallback",
    # OCR settings
    "ocrPriority": ["tesseract", "azure_ocr"],
    "tesseractLang": "deu+eng",
    "azureOcrKey": "",
    "azureOcrEndpoint": "",
    # misc
    "footerTemplate": "\n\n---\nConverted on {{date}} using {{model}}",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _build_generator_priority(settings: dict) -> list[str]:
    """Translate mode + options into a generator_priority list for the engine."""
    mode = settings.get("mode", "simple")
    if mode == "simple":
        return ["standard"]
    if mode == "ocr":
        ocr = list(settings.get("ocrPriority", ["tesseract"]))
        return ocr if ocr else ["tesseract", "standard"]
    if mode == "ai_enhanced":
        ai_mode = settings.get("aiMode", "fallback")
        ocr = list(settings.get("ocrPriority", ["tesseract"]))
        if ai_mode == "enhancement":
            # gemini runs as enhancement pass — put it first so the engine logic picks it up
            return ["gemini"] + ocr
        else:
            # fallback: chain is ocr engines then gemini at the end
            return ocr + ["gemini"]
    return ["standard"]


# ─── Main window ─────────────────────────────────────────────────────────────

class MarkItDownApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MarkItDown Pro Standalone")
        self.setMinimumSize(760, 640)

        self.env_path = Path(__file__).resolve().parent / ".env"
        self.shared_settings_path = Path(__file__).resolve().parent.parent / "markitdown-settings.json"
        self.local_settings_path = Path(__file__).resolve().parent / "markitdown-settings.json"
        self.mode_path = Path(__file__).resolve().parent / "settings-mode.json"

        self.use_separate_settings: bool = self._load_mode()
        self.settings: dict = self._load_settings()
        self.engine: ConversionEngine | None = None

        self._build_ui()

    # ------------------------------------------------------------------ paths

    @property
    def _active_settings_path(self) -> Path:
        return self.local_settings_path if self.use_separate_settings else self.shared_settings_path

    # ---------------------------------------------------------------- persistence

    def _load_mode(self) -> bool:
        try:
            return bool(json.loads(self.mode_path.read_text("utf-8")).get("useSeparateSettings", False))
        except (OSError, json.JSONDecodeError):
            return False

    def _load_api_key(self) -> str:
        if self.env_path.exists():
            load_dotenv(str(self.env_path), override=True)
        return os.getenv("GEMINI_API_KEY", "")

    def _load_azure_ocr_key(self) -> str:
        if self.env_path.exists():
            load_dotenv(str(self.env_path), override=True)
        return os.getenv("AZURE_OCR_KEY", "")

    def _save_api_key(self, key: str) -> None:
        if not self.env_path.exists():
            self.env_path.touch()
        set_key(str(self.env_path), "GEMINI_API_KEY", key)

    def _save_azure_ocr_key(self, key: str) -> None:
        if not self.env_path.exists():
            self.env_path.touch()
        set_key(str(self.env_path), "AZURE_OCR_KEY", key)

    def _load_settings(self) -> dict:
        settings = dict(DEFAULT_SETTINGS)
        try:
            data = json.loads(self._active_settings_path.read_text("utf-8"))
            data.pop("geminiApiKey", None)   # lives in .env only
            data.pop("azureOcrKey", None)    # lives in .env only
            settings.update(data)
        except (OSError, json.JSONDecodeError):
            pass
        settings["geminiApiKey"] = self._load_api_key()
        settings["azureOcrKey"] = self._load_azure_ocr_key()
        return settings

    def _save_settings(self) -> None:
        to_save = {k: v for k, v in self.settings.items()
                   if k not in ("geminiApiKey", "azureOcrKey")}
        try:
            self._active_settings_path.parent.mkdir(parents=True, exist_ok=True)
            self._active_settings_path.write_text(json.dumps(to_save, indent=2), "utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Cannot save settings", str(exc))

    # ---------------------------------------------------------------- UI build

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        self.setCentralWidget(tabs)
        tabs.addTab(self._build_converter_tab(), "Converter")
        tabs.addTab(self._build_settings_tab(), "Settings")

    def _build_converter_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self.drop_label = QLabel('Drop a file here or click "Select file"')
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setStyleSheet(
            "border: 2px dashed #aaa; padding: 30px; border-radius: 4px;"
        )
        layout.addWidget(self.drop_label)

        select_btn = QPushButton("Select file")
        select_btn.clicked.connect(self._on_select_file)
        layout.addWidget(select_btn)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setPlaceholderText("Conversion output will appear here...")
        layout.addWidget(self.output_text)

        return w

    def _build_settings_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # ── 1. Conversion Mode ────────────────────────────────────────────
        mode_group = QGroupBox("Conversion Mode")
        mode_layout = QFormLayout(mode_group)

        self.mode_input = QComboBox()
        self.mode_input.addItems(MODE_LABELS)
        self.mode_input.setCurrentIndex(self._mode_index(self.settings["mode"]))
        self.mode_input.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addRow("Mode:", self.mode_input)

        mode_desc = QLabel(
            "<b>Simple</b> — MarkItDown native (PDF, Word, etc.)<br>"
            "<b>OCR</b> — Tesseract / Azure Vision / Windows OCR fallback chain<br>"
            "<b>AI Enhanced</b> — OCR + Gemini improvement (enhancement or fallback)"
        )
        mode_desc.setWordWrap(True)
        mode_desc.setStyleSheet("color: grey; font-size: 11px;")
        mode_layout.addRow(mode_desc)
        layout.addWidget(mode_group)

        # ── 2. OCR Settings (visible for OCR + AI Enhanced) ───────────────
        self.ocr_group = QGroupBox("OCR Settings")
        ocr_layout = QFormLayout(self.ocr_group)

        # Priority list with move-up/down buttons
        ocr_list_row = QWidget()
        ocr_list_layout = QHBoxLayout(ocr_list_row)
        ocr_list_layout.setContentsMargins(0, 0, 0, 0)

        self.ocr_priority_list = QListWidget()
        self.ocr_priority_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.ocr_priority_list.setMaximumHeight(100)
        self._populate_ocr_list(self.settings.get("ocrPriority", OCR_ENGINE_IDS))
        ocr_list_layout.addWidget(self.ocr_priority_list)

        btn_col = QVBoxLayout()
        up_btn = QPushButton("▲")
        up_btn.setFixedWidth(28)
        up_btn.clicked.connect(self._ocr_move_up)
        down_btn = QPushButton("▼")
        down_btn.setFixedWidth(28)
        down_btn.clicked.connect(self._ocr_move_down)
        btn_col.addWidget(up_btn)
        btn_col.addWidget(down_btn)
        btn_col.addStretch()
        ocr_list_layout.addLayout(btn_col)
        ocr_layout.addRow("Priority chain:", ocr_list_row)

        self.tesseract_lang_input = QLineEdit()
        self.tesseract_lang_input.setPlaceholderText("e.g. deu+eng")
        self.tesseract_lang_input.setText(self.settings.get("tesseractLang", "deu+eng"))
        ocr_layout.addRow("Tesseract language:", self.tesseract_lang_input)

        self.azure_ocr_key_input = QLineEdit()
        self.azure_ocr_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.azure_ocr_key_input.setPlaceholderText("Stored in standalone-app/.env")
        self.azure_ocr_key_input.setText(self.settings.get("azureOcrKey", ""))
        ocr_layout.addRow("Azure OCR Key:", self.azure_ocr_key_input)

        self.azure_ocr_endpoint_input = QLineEdit()
        self.azure_ocr_endpoint_input.setPlaceholderText(
            "https://<resource>.cognitiveservices.azure.com"
        )
        self.azure_ocr_endpoint_input.setText(self.settings.get("azureOcrEndpoint", ""))
        ocr_layout.addRow("Azure OCR Endpoint:", self.azure_ocr_endpoint_input)

        layout.addWidget(self.ocr_group)

        # ── 3. AI Settings (visible for AI Enhanced only) ─────────────────
        self.ai_group = QGroupBox("AI Settings  (Gemini)")
        ai_layout = QFormLayout(self.ai_group)

        self.ai_mode_input = QComboBox()
        self.ai_mode_input.addItems(AI_MODE_LABELS)
        self.ai_mode_input.setCurrentIndex(self._ai_mode_index(self.settings.get("aiMode", "fallback")))
        ai_layout.addRow("AI role:", self.ai_mode_input)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Stored in standalone-app/.env")
        self.api_key_input.setText(self.settings.get("geminiApiKey", ""))
        ai_layout.addRow("Gemini API Key:", self.api_key_input)

        save_key_btn = QPushButton("Save API Keys to .env")
        save_key_btn.clicked.connect(self._on_save_api_keys)
        ai_layout.addRow(save_key_btn)

        self.model_input = QComboBox()
        self.model_input.setEditable(True)
        self.model_input.addItems([
            "gemini-2.0-flash-lite-preview-02-05",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ])
        self.model_input.setCurrentText(self.settings.get("modelName", "gemini-2.0-flash-lite-preview-02-05"))
        ai_layout.addRow("Gemini model:", self.model_input)

        self.prompt_input = QTextEdit()
        self.prompt_input.setFixedHeight(72)
        self.prompt_input.setPlaceholderText("Optional system instructions for Gemini...")
        self.prompt_input.setPlainText(self.settings.get("promptOverride", ""))
        ai_layout.addRow("Prompt override:", self.prompt_input)

        layout.addWidget(self.ai_group)

        # ── 4. Settings Sync ──────────────────────────────────────────────
        sync_group = QGroupBox("Settings Sync")
        sync_layout = QFormLayout(sync_group)

        self.separate_checkbox = QCheckBox("Use separate settings for standalone app")
        self.separate_checkbox.setToolTip(
            "When unchecked, settings are shared with the Obsidian plugin\n"
            "(markitdown-settings.json in the repo root)."
        )
        self.separate_checkbox.setChecked(self.use_separate_settings)
        self.separate_checkbox.toggled.connect(self._on_toggle_separate)
        sync_layout.addRow(self.separate_checkbox)

        self.sync_label = QLabel(self._sync_description())
        self.sync_label.setWordWrap(True)
        self.sync_label.setStyleSheet("color: grey; font-size: 11px;")
        sync_layout.addRow(self.sync_label)
        layout.addWidget(sync_group)

        # ── 5. Save button ────────────────────────────────────────────────
        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(save_btn)

        layout.addStretch()

        # Initial visibility
        self._update_section_visibility(MODE_VALUES[self.mode_input.currentIndex()])

        return w

    # ---------------------------------------------------------------- OCR list helpers

    def _populate_ocr_list(self, priority: list[str]) -> None:
        """Fill the OCR priority list. Engines in priority come first, then the rest unchecked."""
        self.ocr_priority_list.clear()
        seen: set[str] = set()
        for eid in priority:
            if eid in OCR_ENGINE_LABELS:
                item = QListWidgetItem(OCR_ENGINE_LABELS[eid])
                item.setData(Qt.ItemDataRole.UserRole, eid)
                item.setCheckState(Qt.CheckState.Checked)
                self.ocr_priority_list.addItem(item)
                seen.add(eid)
        for eid, label in _OCR_OPTIONS:
            if eid not in seen:
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, eid)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.ocr_priority_list.addItem(item)

    def _ocr_priority_value(self) -> list[str]:
        result = []
        for i in range(self.ocr_priority_list.count()):
            item = self.ocr_priority_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def _ocr_move_up(self) -> None:
        row = self.ocr_priority_list.currentRow()
        if row > 0:
            item = self.ocr_priority_list.takeItem(row)
            self.ocr_priority_list.insertItem(row - 1, item)
            self.ocr_priority_list.setCurrentRow(row - 1)

    def _ocr_move_down(self) -> None:
        row = self.ocr_priority_list.currentRow()
        if row < self.ocr_priority_list.count() - 1:
            item = self.ocr_priority_list.takeItem(row)
            self.ocr_priority_list.insertItem(row + 1, item)
            self.ocr_priority_list.setCurrentRow(row + 1)

    # ---------------------------------------------------------------- visibility

    def _update_section_visibility(self, mode: str) -> None:
        self.ocr_group.setVisible(mode in ("ocr", "ai_enhanced"))
        self.ai_group.setVisible(mode == "ai_enhanced")

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _mode_index(mode: str) -> int:
        try:
            return MODE_VALUES.index(mode)
        except ValueError:
            return 0

    @staticmethod
    def _ai_mode_index(ai_mode: str) -> int:
        try:
            return AI_MODE_VALUES.index(ai_mode)
        except ValueError:
            return 0

    def _sync_description(self) -> str:
        if self.use_separate_settings:
            return "Saving to: standalone-app/markitdown-settings.json (standalone only)"
        return "Saving to: markitdown-settings.json (shared with Obsidian plugin)"

    # ---------------------------------------------------------------- slots

    def _on_mode_changed(self, index: int) -> None:
        self._update_section_visibility(MODE_VALUES[index])

    def _on_save_api_keys(self) -> None:
        gemini_key = self.api_key_input.text().strip()
        azure_key = self.azure_ocr_key_input.text().strip()
        self._save_api_key(gemini_key)
        self._save_azure_ocr_key(azure_key)
        self.settings["geminiApiKey"] = gemini_key
        self.settings["azureOcrKey"] = azure_key
        self.engine = None
        self.output_text.setText("API Keys saved to .env.")

    def _on_save_settings(self) -> None:
        mode = MODE_VALUES[self.mode_input.currentIndex()]
        self.settings.update({
            "mode": mode,
            "modelName": self.model_input.currentText().strip(),
            "promptOverride": self.prompt_input.toPlainText().strip(),
            "aiMode": AI_MODE_VALUES[self.ai_mode_input.currentIndex()],
            "ocrPriority": self._ocr_priority_value(),
            "tesseractLang": self.tesseract_lang_input.text().strip(),
            "azureOcrEndpoint": self.azure_ocr_endpoint_input.text().strip(),
        })
        self._save_settings()
        self.engine = None
        self.output_text.setText(f"Settings saved to {self._active_settings_path.name}.")

    def _on_toggle_separate(self, separate: bool) -> None:
        self.use_separate_settings = separate
        try:
            self.mode_path.write_text(json.dumps({"useSeparateSettings": separate}), "utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Cannot save settings mode", str(exc))
            return
        self.settings = self._load_settings()
        # Reload UI fields
        self.mode_input.setCurrentIndex(self._mode_index(self.settings["mode"]))
        self.api_key_input.setText(self.settings.get("geminiApiKey", ""))
        self.azure_ocr_key_input.setText(self.settings.get("azureOcrKey", ""))
        self.azure_ocr_endpoint_input.setText(self.settings.get("azureOcrEndpoint", ""))
        self.model_input.setCurrentText(self.settings.get("modelName", ""))
        self.prompt_input.setPlainText(self.settings.get("promptOverride", ""))
        self.ai_mode_input.setCurrentIndex(self._ai_mode_index(self.settings.get("aiMode", "fallback")))
        self._populate_ocr_list(self.settings.get("ocrPriority", OCR_ENGINE_IDS))
        self.tesseract_lang_input.setText(self.settings.get("tesseractLang", "deu+eng"))
        self.sync_label.setText(self._sync_description())

    def _on_select_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Select file to convert")
        if file_path:
            self._convert(file_path)

    def _convert(self, file_path: str) -> None:
        # Collect current UI state into settings
        mode = MODE_VALUES[self.mode_input.currentIndex()]
        self.settings.update({
            "mode": mode,
            "geminiApiKey": self.api_key_input.text().strip(),
            "modelName": self.model_input.currentText().strip(),
            "promptOverride": self.prompt_input.toPlainText().strip(),
            "aiMode": AI_MODE_VALUES[self.ai_mode_input.currentIndex()],
            "ocrPriority": self._ocr_priority_value(),
            "tesseractLang": self.tesseract_lang_input.text().strip(),
            "azureOcrKey": self.azure_ocr_key_input.text().strip(),
            "azureOcrEndpoint": self.azure_ocr_endpoint_input.text().strip(),
        })

        generator_priority = _build_generator_priority(self.settings)

        # For AI Enhanced mode the engine needs to know the ai_mode
        ai_mode = self.settings.get("aiMode", "fallback") if mode == "ai_enhanced" else "fallback"

        self.engine = ConversionEngine(
            api_key=self.settings["geminiApiKey"],
            model_name=self.settings["modelName"],
            prompt_override=self.settings["promptOverride"],
            generator_priority=generator_priority,
            ai_mode=ai_mode,
            azure_ocr_key=self.settings.get("azureOcrKey") or None,
            azure_ocr_endpoint=self.settings.get("azureOcrEndpoint") or None,
            tesseract_lang=self.settings.get("tesseractLang", "deu+eng"),
        )

        self.output_text.setText(f"Converting {Path(file_path).name}...")
        QApplication.processEvents()
        self.output_text.setText(self.engine.convert(file_path))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MarkItDownApp()
    window.show()
    sys.exit(app.exec())
