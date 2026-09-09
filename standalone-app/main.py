import json
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv, set_key
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QTextEdit, QVBoxLayout, QWidget, QTabWidget,
)
from engine.conversionEngine import ConversionEngine
from session_state import SessionFileState, format_conversion_error

# ─── OCR sub-engine options ───────────────────────────────────────────────────

_OCR_ENGINES: list[tuple[str, str]] = [
    ("azure_document_intelligence", "Azure Document Intelligence  (cloud)"),
    ("tesseract", "Tesseract  (local)"),
    ("azure_ocr", "Azure Computer Vision  (cloud)"),
]
if platform.system() == "Windows":
    _OCR_ENGINES.append(("win_ocr", "Windows OCR  (local, Windows only)"))

OCR_ENGINE_IDS    = [eid for eid, _ in _OCR_ENGINES]
OCR_ENGINE_LABELS = {eid: lbl for eid, lbl in _OCR_ENGINES}

# The three top-level blocks, in their default priority order
_BLOCKS = [
    ("markitdown", "MarkItDown"),
    ("ocr",        "OCR"),
    ("ai",         "AI  (Gemini)"),
]

DEFAULT_SETTINGS: dict = {
    # which top-level blocks are enabled
    "useMarkitdown": True,
    "useOcr":        False,
    "useAi":         False,
    # priority order of blocks: list of block-ids
    "blockPriority": ["markitdown", "ocr", "ai"],
    # OCR sub-engine priority (subset of OCR_ENGINE_IDS)
    "ocrPriority":   ["azure_document_intelligence", "tesseract", "azure_ocr", "win_ocr"],
    # AI extras
    "aiAutoDetect":  False,
    "aiImprove":     False,
    # credentials & model
    "geminiApiKey":      "",
    "azureOcrKey":       "",
    "azureOcrEndpoint":  "",
    "azureDocumentIntelligenceKey": "",
    "azureDocumentIntelligenceEndpoint": "",
    "tesseractLang":     "deu+eng",
    "tesseractCmd":      "",
    "modelName":         "gemini-3.1-flash-lite",
    "promptOverride":    "",
    # misc
    "footerTemplate": "\n\n---\nConverted on {{date}} using {{model}}",
}


def _build_enabled_generators(s: dict) -> list[str]:
    """
    Translate the 3-block settings into a flat ordered generator list
    that ConversionEngine.enabled_generators accepts.
    """
    result: list[str] = []
    for block in s.get("blockPriority", ["markitdown", "ocr", "ai"]):
        if block == "markitdown" and s.get("useMarkitdown", True):
            result.append("markitdown")
        elif block == "ocr" and s.get("useOcr", False):
            for eid in s.get(
                "ocrPriority",
                ["azure_document_intelligence", "tesseract", "azure_ocr", "win_ocr"],
            ):
                result.append(eid)
        elif block == "ai" and s.get("useAi", False):
            # Keep Gemini in the fallback chain even when auto-detect or
            # post-processing is enabled. Both modes still need a direct AI
            # fallback when MarkItDown/OCR produce no text.
            result.append("gemini")
    return result or ["markitdown"]


# ─── Main window ──────────────────────────────────────────────────────────────

class MarkItDownApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MarkItDown Pro Standalone")
        self.setMinimumSize(740, 680)

        self.env_path    = Path(__file__).resolve().parent / ".env"
        self.shared_path = Path(__file__).resolve().parent.parent / "markitdown-settings.json"
        self.local_path  = Path(__file__).resolve().parent / "markitdown-settings.json"
        self.mode_path   = Path(__file__).resolve().parent / "settings-mode.json"

        self.use_separate: bool = self._load_separate_flag()
        self.settings: dict     = self._load_settings()
        self.engine: ConversionEngine | None = None
        self.session_file = SessionFileState()

        self._build_ui()

    # ── persistence ───────────────────────────────────────────────────────────

    @property
    def _settings_path(self) -> Path:
        return self.local_path if self.use_separate else self.shared_path

    def _load_separate_flag(self) -> bool:
        try:
            return bool(json.loads(self.mode_path.read_text("utf-8")).get("useSeparateSettings", False))
        except (OSError, json.JSONDecodeError):
            return False

    def _load_env_key(self, var: str) -> str:
        if self.env_path.exists():
            load_dotenv(str(self.env_path), override=True)
        return os.getenv(var, "")

    def _save_env_key(self, var: str, value: str) -> None:
        if not self.env_path.exists():
            self.env_path.touch()
        set_key(str(self.env_path), var, value)

    def _load_settings(self) -> dict:
        s = dict(DEFAULT_SETTINGS)
        try:
            data = json.loads(self._settings_path.read_text("utf-8"))
            for k in (
                "geminiApiKey",
                "azureOcrKey",
                "azureDocumentIntelligenceKey",
            ):
                data.pop(k, None)
            s.update(data)
        except (OSError, json.JSONDecodeError):
            pass
        retired_models = {
            "gemini-2.0-flash-lite-preview-02-05",
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        }
        if s.get("modelName") in retired_models:
            s["modelName"] = DEFAULT_SETTINGS["modelName"]
        if s.get("ocrPriority") == [
            "tesseract",
            "azure_ocr",
            "azure_document_intelligence",
        ]:
            s["ocrPriority"] = list(DEFAULT_SETTINGS["ocrPriority"])
        s["geminiApiKey"] = self._load_env_key("GEMINI_API_KEY")
        s["azureOcrKey"]  = self._load_env_key("AZURE_OCR_KEY")
        s["azureDocumentIntelligenceKey"] = self._load_env_key(
            "AZURE_DOCUMENT_INTELLIGENCE_KEY"
        )
        return s

    def _save_settings(self) -> None:
        skip = {"geminiApiKey", "azureOcrKey", "azureDocumentIntelligenceKey"}
        to_save = {k: v for k, v in self.settings.items() if k not in skip}
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            self._settings_path.write_text(json.dumps(to_save, indent=2), "utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Cannot save settings", str(exc))

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        self.setCentralWidget(tabs)
        tabs.addTab(self._build_converter_tab(), "Converter")
        tabs.addTab(self._build_settings_tab(),  "Settings")

    def _build_converter_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.drop_label = QLabel('Drop a file here or click "Select file"')
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setStyleSheet("border: 2px dashed #aaa; padding: 30px; border-radius: 4px;")
        lay.addWidget(self.drop_label)
        self.last_file_label = QLabel("No file selected in this session.")
        self.last_file_label.setWordWrap(True)
        lay.addWidget(self.last_file_label)
        btn = QPushButton("Select file")
        btn.clicked.connect(self._on_select_file)
        lay.addWidget(btn)
        self.start_conversion_btn = QPushButton("Start conversion")
        self.start_conversion_btn.setEnabled(False)
        self.start_conversion_btn.clicked.connect(self._on_start_conversion)
        lay.addWidget(self.start_conversion_btn)
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setPlaceholderText("Conversion output will appear here…")
        lay.addWidget(self.output_text)
        return w

    def _build_settings_tab(self) -> QWidget:
        w = QWidget()
        outer_lay = QVBoxLayout(w)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)

        settings_content = QWidget()
        lay = QVBoxLayout(settings_content)

        # ── 1. Enable / priority ──────────────────────────────────────────────
        top_group = QGroupBox("Methods — enable and set priority")
        top_lay   = QVBoxLayout(top_group)

        top_lay.addWidget(QLabel(
            "Check the methods you want to use. Drag or use ▲▼ to set the fallback order."
        ))

        row_w  = QWidget()
        row_lay = QHBoxLayout(row_w)
        row_lay.setContentsMargins(0, 0, 0, 0)

        self.block_list = QListWidget()
        self.block_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.block_list.setFixedHeight(96)
        self.block_list.itemChanged.connect(self._on_block_check_changed)
        self._populate_block_list()
        row_lay.addWidget(self.block_list)

        btn_col = QVBoxLayout()
        for lbl, fn in [("▲", self._block_move_up), ("▼", self._block_move_down)]:
            b = QPushButton(lbl)
            b.setFixedWidth(28)
            b.clicked.connect(fn)
            btn_col.addWidget(b)
        btn_col.addStretch()
        row_lay.addLayout(btn_col)
        top_lay.addWidget(row_w)
        lay.addWidget(top_group)

        # ── 2. OCR sub-options (shown when OCR checked) ───────────────────────
        self.ocr_group = QGroupBox("OCR — sub-engine priority")
        ocr_lay = QVBoxLayout(self.ocr_group)

        ocr_row_w  = QWidget()
        ocr_row_lay = QHBoxLayout(ocr_row_w)
        ocr_row_lay.setContentsMargins(0, 0, 0, 0)

        self.ocr_list = QListWidget()
        self.ocr_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.ocr_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._populate_ocr_list(self.settings.get("ocrPriority", OCR_ENGINE_IDS))
        ocr_row_lay.addWidget(self.ocr_list)

        ocr_btn_col = QVBoxLayout()
        for lbl, fn in [("▲", self._ocr_move_up), ("▼", self._ocr_move_down)]:
            b = QPushButton(lbl)
            b.setFixedWidth(28)
            b.clicked.connect(fn)
            ocr_btn_col.addWidget(b)
        ocr_btn_col.addStretch()
        ocr_row_lay.addLayout(ocr_btn_col)
        ocr_lay.addWidget(ocr_row_w)

        ocr_form = QFormLayout()
        self.tess_lang_input = QLineEdit(self.settings.get("tesseractLang", "deu+eng"))
        self.tess_lang_input.setPlaceholderText("e.g. deu+eng")
        ocr_form.addRow("Tesseract language:", self.tess_lang_input)
        self.azure_endpoint_input = QLineEdit(self.settings.get("azureOcrEndpoint", ""))
        self.azure_endpoint_input.setPlaceholderText("https://<resource>.cognitiveservices.azure.com")
        ocr_form.addRow("Azure Computer Vision endpoint:", self.azure_endpoint_input)

        self.azure_key_input = QLineEdit(self.settings.get("azureOcrKey", ""))
        self.azure_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.azure_key_input.setPlaceholderText("Required for Azure Computer Vision")
        ocr_form.addRow("Azure Computer Vision key:", self.azure_key_input)

        self.azure_di_endpoint_input = QLineEdit(
            self.settings.get("azureDocumentIntelligenceEndpoint", "")
        )
        self.azure_di_endpoint_input.setPlaceholderText(
            "https://<resource>.cognitiveservices.azure.com"
        )
        ocr_form.addRow("Azure Document Intelligence endpoint:", self.azure_di_endpoint_input)

        self.azure_di_key_input = QLineEdit(
            self.settings.get("azureDocumentIntelligenceKey", "")
        )
        self.azure_di_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.azure_di_key_input.setPlaceholderText("Required for Azure Document Intelligence")
        ocr_form.addRow("Azure Document Intelligence key:", self.azure_di_key_input)

        save_cred_btn = QPushButton("Save API Keys to .env")
        save_cred_btn.clicked.connect(self._on_save_credentials)
        ocr_form.addRow(save_cred_btn)
        ocr_lay.addLayout(ocr_form)
        lay.addWidget(self.ocr_group)

        # ── 3. AI sub-options (shown when AI checked) ─────────────────────────
        self.ai_group = QGroupBox("AI  (Gemini) — options")
        ai_lay = QVBoxLayout(self.ai_group)

        self.ai_auto_detect_cb = QCheckBox(
            "Auto-Detect: Gemini inspects the file and picks the best method"
        )
        self.ai_auto_detect_cb.setChecked(self.settings.get("aiAutoDetect", False))
        ai_lay.addWidget(self.ai_auto_detect_cb)

        self.ai_improve_cb = QCheckBox(
            "Improve: Gemini post-processes every result to clean up and improve quality"
        )
        self.ai_improve_cb.setChecked(self.settings.get("aiImprove", False))
        ai_lay.addWidget(self.ai_improve_cb)

        ai_form = QFormLayout()
        self.gemini_key_input = QLineEdit(self.settings.get("geminiApiKey", ""))
        self.gemini_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_input.setPlaceholderText("Stored in .env")
        ai_form.addRow("Gemini API Key:", self.gemini_key_input)

        self.model_input = QComboBox()
        self.model_input.setEditable(True)
        self.model_input.addItems([
            "gemini-3.1-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.5-flash-lite",
        ])
        self.model_input.setCurrentText(self.settings.get("modelName", "gemini-3.1-flash-lite"))
        ai_form.addRow("Model:", self.model_input)

        self.prompt_input = QTextEdit()
        self.prompt_input.setFixedHeight(60)
        self.prompt_input.setPlaceholderText("Custom system instruction (leave empty for built-in prompt)…")
        self.prompt_input.setPlainText(self.settings.get("promptOverride", ""))
        ai_form.addRow("Prompt override:", self.prompt_input)
        ai_lay.addLayout(ai_form)
        lay.addWidget(self.ai_group)

        # ── 4. Sync ───────────────────────────────────────────────────────────
        sync_group = QGroupBox("Settings Sync")
        sync_form  = QFormLayout(sync_group)
        self.separate_cb = QCheckBox("Use separate settings file for standalone app")
        self.separate_cb.setChecked(self.use_separate)
        self.separate_cb.toggled.connect(self._on_toggle_separate)
        sync_form.addRow(self.separate_cb)
        self.sync_label = QLabel(self._sync_description())
        self.sync_label.setWordWrap(True)
        self.sync_label.setStyleSheet("color: grey; font-size: 11px;")
        sync_form.addRow(self.sync_label)
        lay.addWidget(sync_group)

        # ── 5. Save ───────────────────────────────────────────────────────────
        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(self._on_save_settings)
        lay.addWidget(save_btn)
        lay.addStretch()

        # Apply initial sub-section visibility
        self._update_subgroup_visibility()

        settings_scroll.setWidget(settings_content)
        outer_lay.addWidget(settings_scroll)
        return w

    # ── block list helpers ────────────────────────────────────────────────────

    def _populate_block_list(self) -> None:
        enabled_set = set()
        if self.settings.get("useMarkitdown", True):
            enabled_set.add("markitdown")
        if self.settings.get("useOcr", False):
            enabled_set.add("ocr")
        if self.settings.get("useAi", False):
            enabled_set.add("ai")

        priority = self.settings.get("blockPriority", ["markitdown", "ocr", "ai"])
        # Build ordered list: priority-ordered first, then any remaining
        all_ids = [b[0] for b in _BLOCKS]
        ordered = [bid for bid in priority if bid in all_ids]
        ordered += [bid for bid in all_ids if bid not in ordered]

        labels = {b[0]: b[1] for b in _BLOCKS}
        self.block_list.blockSignals(True)
        self.block_list.clear()
        for bid in ordered:
            item = QListWidgetItem(labels[bid])
            item.setData(Qt.ItemDataRole.UserRole, bid)
            item.setCheckState(
                Qt.CheckState.Checked if bid in enabled_set else Qt.CheckState.Unchecked
            )
            self.block_list.addItem(item)
        self.block_list.blockSignals(False)

    def _block_priority(self) -> list[str]:
        return [
            self.block_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.block_list.count())
        ]

    def _block_enabled(self, bid: str) -> bool:
        for i in range(self.block_list.count()):
            item = self.block_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == bid:
                return item.checkState() == Qt.CheckState.Checked
        return False

    def _block_move_up(self) -> None:
        row = self.block_list.currentRow()
        if row > 0:
            item = self.block_list.takeItem(row)
            self.block_list.insertItem(row - 1, item)
            self.block_list.setCurrentRow(row - 1)

    def _block_move_down(self) -> None:
        row = self.block_list.currentRow()
        if row < self.block_list.count() - 1:
            item = self.block_list.takeItem(row)
            self.block_list.insertItem(row + 1, item)
            self.block_list.setCurrentRow(row + 1)

    # ── OCR list helpers ──────────────────────────────────────────────────────

    def _populate_ocr_list(self, priority: list[str]) -> None:
        self.ocr_list.clear()
        seen: set[str] = set()
        for eid in priority:
            if eid in OCR_ENGINE_LABELS:
                item = QListWidgetItem(OCR_ENGINE_LABELS[eid])
                item.setData(Qt.ItemDataRole.UserRole, eid)
                item.setCheckState(Qt.CheckState.Checked)
                self.ocr_list.addItem(item)
                seen.add(eid)
        for eid, lbl in _OCR_ENGINES:
            if eid not in seen:
                item = QListWidgetItem(lbl)
                item.setData(Qt.ItemDataRole.UserRole, eid)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.ocr_list.addItem(item)
        self._fit_ocr_list_height()

    def _fit_ocr_list_height(self) -> None:
        if self.ocr_list.count() == 0:
            self.ocr_list.setFixedHeight(0)
            return

        row_height = self.ocr_list.sizeHintForRow(0)
        if row_height <= 0:
            row_height = self.ocr_list.fontMetrics().height() + 4
        frame_height = 2 * self.ocr_list.frameWidth()
        self.ocr_list.setFixedHeight(row_height * self.ocr_list.count() + frame_height)

    def _ocr_priority_value(self) -> list[str]:
        result = []
        for i in range(self.ocr_list.count()):
            item = self.ocr_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def _ocr_move_up(self) -> None:
        row = self.ocr_list.currentRow()
        if row > 0:
            item = self.ocr_list.takeItem(row)
            self.ocr_list.insertItem(row - 1, item)
            self.ocr_list.setCurrentRow(row - 1)

    def _ocr_move_down(self) -> None:
        row = self.ocr_list.currentRow()
        if row < self.ocr_list.count() - 1:
            item = self.ocr_list.takeItem(row)
            self.ocr_list.insertItem(row + 1, item)
            self.ocr_list.setCurrentRow(row + 1)

    # ── visibility ────────────────────────────────────────────────────────────

    def _update_subgroup_visibility(self) -> None:
        self.ocr_group.setVisible(self._block_enabled("ocr"))
        self.ai_group.setVisible(self._block_enabled("ai"))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _sync_description(self) -> str:
        if self.use_separate:
            return "Saving to: standalone-app/markitdown-settings.json (standalone only)"
        return "Saving to: markitdown-settings.json (shared with Obsidian plugin)"

    def _collect_from_ui(self) -> None:
        self.settings.update({
            "useMarkitdown":    self._block_enabled("markitdown"),
            "useOcr":           self._block_enabled("ocr"),
            "useAi":            self._block_enabled("ai"),
            "blockPriority":    self._block_priority(),
            "ocrPriority":      self._ocr_priority_value(),
            "aiAutoDetect":     self.ai_auto_detect_cb.isChecked(),
            "aiImprove":        self.ai_improve_cb.isChecked(),
            "geminiApiKey":     self.gemini_key_input.text().strip(),
            "azureOcrKey":      self.azure_key_input.text().strip(),
            "azureOcrEndpoint": self.azure_endpoint_input.text().strip(),
            "azureDocumentIntelligenceKey": self.azure_di_key_input.text().strip(),
            "azureDocumentIntelligenceEndpoint": self.azure_di_endpoint_input.text().strip(),
            "tesseractLang":    self.tess_lang_input.text().strip(),
            "modelName":        self.model_input.currentText().strip(),
            "promptOverride":   self.prompt_input.toPlainText().strip(),
        })

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_block_check_changed(self, _item: QListWidgetItem) -> None:
        self._update_subgroup_visibility()

    def _on_save_credentials(self) -> None:
        gemini = self.gemini_key_input.text().strip()
        azure  = self.azure_key_input.text().strip()
        azure_di = self.azure_di_key_input.text().strip()
        self._save_env_key("GEMINI_API_KEY", gemini)
        self._save_env_key("AZURE_OCR_KEY",  azure)
        self._save_env_key("AZURE_DOCUMENT_INTELLIGENCE_KEY", azure_di)
        self.settings["geminiApiKey"] = gemini
        self.settings["azureOcrKey"]  = azure
        self.settings["azureDocumentIntelligenceKey"] = azure_di
        self.engine = None
        self.output_text.setText("API keys saved to .env.")

    def _on_save_settings(self) -> None:
        self._collect_from_ui()
        self._save_settings()
        self.engine = None
        self.output_text.setText(f"Settings saved to {self._settings_path.name}.")

    def _on_toggle_separate(self, separate: bool) -> None:
        self.use_separate = separate
        try:
            self.mode_path.write_text(json.dumps({"useSeparateSettings": separate}), "utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Cannot save mode", str(exc))
            return
        self.settings = self._load_settings()
        # Reload UI
        self._populate_block_list()
        self._populate_ocr_list(self.settings.get("ocrPriority", OCR_ENGINE_IDS))
        self.ai_auto_detect_cb.setChecked(self.settings.get("aiAutoDetect", False))
        self.ai_improve_cb.setChecked(self.settings.get("aiImprove", False))
        self.gemini_key_input.setText(self.settings.get("geminiApiKey", ""))
        self.azure_key_input.setText(self.settings.get("azureOcrKey", ""))
        self.azure_endpoint_input.setText(self.settings.get("azureOcrEndpoint", ""))
        self.azure_di_key_input.setText(self.settings.get("azureDocumentIntelligenceKey", ""))
        self.azure_di_endpoint_input.setText(
            self.settings.get("azureDocumentIntelligenceEndpoint", "")
        )
        self.tess_lang_input.setText(self.settings.get("tesseractLang", "deu+eng"))
        self.model_input.setCurrentText(self.settings.get("modelName", ""))
        self.prompt_input.setPlainText(self.settings.get("promptOverride", ""))
        self.sync_label.setText(self._sync_description())
        self._update_subgroup_visibility()

    def _on_select_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Select file to convert")
        if file_path:
            self.session_file.remember(file_path)
            self.last_file_label.setText(f"Last selected file: {self.session_file.last_file_path}")
            self.start_conversion_btn.setEnabled(True)
            self.output_text.clear()

    def _on_start_conversion(self) -> None:
        file_path = self.session_file.last_file_path
        if not file_path:
            self.output_text.setPlainText("Select a file before starting the conversion.")
            return
        self._convert(file_path)

    def _convert(self, file_path: str) -> None:
        try:
            self.output_text.setPlainText(f"Converting {Path(file_path).name}…")
            QApplication.processEvents()
            self._collect_from_ui()
            enabled_generators = _build_enabled_generators(self.settings)
            use_ai = self.settings.get("useAi", False)

            self.engine = ConversionEngine(
                enabled_generators=enabled_generators,
                ai_improve=use_ai and self.settings.get("aiImprove", False),
                ai_auto_detect=use_ai and self.settings.get("aiAutoDetect", False),
                api_key=self.settings.get("geminiApiKey") or None,
                model_name=self.settings.get("modelName", "gemini-3.1-flash-lite"),
                prompt_override=self.settings.get("promptOverride", ""),
                azure_ocr_key=self.settings.get("azureOcrKey") or None,
                azure_ocr_endpoint=self.settings.get("azureOcrEndpoint") or None,
                azure_document_intelligence_key=self.settings.get(
                    "azureDocumentIntelligenceKey"
                ) or None,
                azure_document_intelligence_endpoint=self.settings.get(
                    "azureDocumentIntelligenceEndpoint"
                ) or None,
                tesseract_lang=self.settings.get("tesseractLang", "deu+eng"),
                tesseract_cmd=self.settings.get("tesseractCmd") or None,
            )
            result = self.engine.convert(file_path)
            if not result or not result.strip():
                raise RuntimeError("No text extracted. Check the enabled methods and OCR settings.")
            if result.lstrip().startswith("Error:"):
                self.output_text.setPlainText(result.strip())
                return
            self.output_text.setPlainText(result)
        except Exception as exc:
            self.output_text.setPlainText(format_conversion_error(file_path, exc))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MarkItDownApp()
    window.show()
    sys.exit(app.exec())
