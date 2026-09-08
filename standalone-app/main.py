import json
import os
import sys
from pathlib import Path

# Add the repo root to sys.path so the shared engine package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv, set_key
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QTextEdit, QVBoxLayout, QWidget, QTabWidget,
)
from engine.conversionEngine import ConversionEngine

DEFAULT_SETTINGS: dict = {
    "modelName": "gemini-2.0-flash-lite-preview-02-05",
    "promptOverride": "",
    "footerTemplate": "\n\n---\nConverted on {{date}} using {{model}}",
    "generatorPriority": ["gemini", "standard"],
}

PRIORITY_LABELS = [
    "Gemini -> Standard",
    "Standard -> Gemini",
    "Gemini only",
    "Standard only",
]
PRIORITY_VALUES: list[list[str]] = [
    ["gemini", "standard"],
    ["standard", "gemini"],
    ["gemini"],
    ["standard"],
]


class MarkItDownApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MarkItDown Pro Standalone")
        self.setMinimumSize(720, 600)

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

    def _save_api_key(self, key: str) -> None:
        if not self.env_path.exists():
            self.env_path.touch()
        set_key(str(self.env_path), "GEMINI_API_KEY", key)

    def _load_settings(self) -> dict:
        settings = dict(DEFAULT_SETTINGS)
        try:
            data = json.loads(self._active_settings_path.read_text("utf-8"))
            data.pop("geminiApiKey", None)  # API key lives in .env only
            settings.update(data)
        except (OSError, json.JSONDecodeError):
            pass
        settings["geminiApiKey"] = self._load_api_key()
        return settings

    def _save_settings(self) -> None:
        to_save = {k: v for k, v in self.settings.items() if k != "geminiApiKey"}
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

        # --- API Keys --------------------------------------------------------
        api_group = QGroupBox("API Keys")
        api_layout = QFormLayout(api_group)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Stored in standalone-app/.env")
        self.api_key_input.setText(self._load_api_key())
        api_layout.addRow("Gemini API Key:", self.api_key_input)

        save_key_btn = QPushButton("Save API Key to .env")
        save_key_btn.clicked.connect(self._on_save_api_key)
        api_layout.addRow(save_key_btn)

        layout.addWidget(api_group)

        # --- Model & Conversion ----------------------------------------------
        model_group = QGroupBox("Model & Conversion")
        model_layout = QFormLayout(model_group)

        self.model_input = QComboBox()
        self.model_input.setEditable(True)
        self.model_input.addItems([
            "gemini-2.0-flash-lite-preview-02-05",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ])
        self.model_input.setCurrentText(self.settings["modelName"])
        model_layout.addRow("Gemini model:", self.model_input)

        self.prompt_input = QTextEdit()
        self.prompt_input.setFixedHeight(72)
        self.prompt_input.setPlaceholderText("Optional system instructions passed to Gemini...")
        self.prompt_input.setPlainText(self.settings["promptOverride"])
        model_layout.addRow("Gemini prompt:", self.prompt_input)

        self.priority_input = QComboBox()
        self.priority_input.addItems(PRIORITY_LABELS)
        self.priority_input.setCurrentIndex(self._priority_index(self.settings["generatorPriority"]))
        model_layout.addRow("Generator priority:", self.priority_input)

        layout.addWidget(model_group)

        # --- Sync mode -------------------------------------------------------
        sync_group = QGroupBox("Settings Sync")
        sync_layout = QFormLayout(sync_group)

        self.separate_checkbox = QCheckBox("Use separate settings for standalone app")
        self.separate_checkbox.setToolTip(
            "When unchecked, settings are shared with the Obsidian plugin\n"
            "(markitdown-settings.json in the repo root)."
        )
        self.separate_checkbox.setChecked(self.use_separate_settings)
        self.separate_checkbox.toggled.connect(self._on_toggle_mode)
        sync_layout.addRow(self.separate_checkbox)

        self.sync_label = QLabel(self._sync_description())
        self.sync_label.setWordWrap(True)
        self.sync_label.setStyleSheet("color: grey; font-size: 11px;")
        sync_layout.addRow(self.sync_label)

        layout.addWidget(sync_group)

        # --- Save button -----------------------------------------------------
        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(save_btn)

        layout.addStretch()
        return w

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _priority_index(priority: list[str]) -> int:
        try:
            return PRIORITY_VALUES.index(list(priority))
        except ValueError:
            return 0

    def _sync_description(self) -> str:
        if self.use_separate_settings:
            return "Saving to: standalone-app/markitdown-settings.json (standalone only)"
        return "Saving to: markitdown-settings.json (shared with Obsidian plugin)"

    # ---------------------------------------------------------------- slots

    def _on_save_api_key(self) -> None:
        key = self.api_key_input.text().strip()
        self._save_api_key(key)
        self.settings["geminiApiKey"] = key
        self.engine = None
        self.output_text.setText("API Key saved to .env.")

    def _on_save_settings(self) -> None:
        self.settings.update({
            "modelName": self.model_input.currentText().strip(),
            "promptOverride": self.prompt_input.toPlainText().strip(),
            "generatorPriority": PRIORITY_VALUES[self.priority_input.currentIndex()],
        })
        self._save_settings()
        self.engine = None
        self.output_text.setText(f"Settings saved to {self._active_settings_path.name}.")

    def _on_toggle_mode(self, separate: bool) -> None:
        self.use_separate_settings = separate
        try:
            self.mode_path.write_text(json.dumps({"useSeparateSettings": separate}), "utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Cannot save settings mode", str(exc))
            return
        self.settings = self._load_settings()
        self.api_key_input.setText(self.settings["geminiApiKey"])
        self.model_input.setCurrentText(self.settings["modelName"])
        self.prompt_input.setPlainText(self.settings["promptOverride"])
        self.priority_input.setCurrentIndex(self._priority_index(self.settings["generatorPriority"]))
        self.sync_label.setText(self._sync_description())

    def _on_select_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Select file to convert")
        if file_path:
            self._convert(file_path)

    def _convert(self, file_path: str) -> None:
        self.settings.update({
            "geminiApiKey": self.api_key_input.text().strip(),
            "modelName": self.model_input.currentText().strip(),
            "promptOverride": self.prompt_input.toPlainText().strip(),
            "generatorPriority": PRIORITY_VALUES[self.priority_input.currentIndex()],
        })
        self.engine = ConversionEngine(
            api_key=self.settings["geminiApiKey"],
            model_name=self.settings["modelName"],
            prompt_override=self.settings["promptOverride"],
            generator_priority=self.settings["generatorPriority"],
        )
        self.output_text.setText(f"Converting {Path(file_path).name}...")
        QApplication.processEvents()
        self.output_text.setText(self.engine.convert(file_path))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MarkItDownApp()
    window.show()
    sys.exit(app.exec())
