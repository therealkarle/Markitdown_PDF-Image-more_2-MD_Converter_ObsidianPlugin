import json
import os
import sys
from pathlib import Path
import dotenv

# Add the repo root to sys.path so the shared engine package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)
from engine.conversionEngine import ConversionEngine

DEFAULT_SETTINGS = {
    "modelName": "gemini-2.0-flash-lite-preview-02-05",
    "promptOverride": "",
    "footerTemplate": "\n\n---\nConverted on {{date}} using {{model}}",
    "generatorPriority": ["gemini", "standard"],
}


class MarkItDownApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MarkItDown Pro Standalone")
        self.setMinimumSize(700, 560)
        self.shared_settings_path = Path(__file__).resolve().parent.parent / "markitdown-settings.json"
        self.local_settings_path = Path(__file__).resolve().parent / "markitdown-settings.json"
        self.mode_path = Path(__file__).resolve().parent / "settings-mode.json"
        self.use_separate_settings = self.load_settings_mode()
        self.settings = self.load_settings()
        self.engine = None
        self.init_ui()
        self.populate_settings_form()

    @property
    def active_settings_path(self) -> Path:
        return self.local_settings_path if self.use_separate_settings else self.shared_settings_path

    def load_settings_mode(self) -> bool:
        try:
            return bool(json.loads(self.mode_path.read_text(encoding="utf-8")).get("useSeparateSettings", False))
        except (OSError, json.JSONDecodeError):
            return False

    def load_settings(self) -> dict:
        # Don't ever load an API key from JSON, use .env only!
        settings = dict(DEFAULT_SETTINGS)
        try:
            loaded = json.loads(self.active_settings_path.read_text(encoding="utf-8"))
            loaded.pop('geminiApiKey', None)
            settings.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
        settings['geminiApiKey'] = self.load_api_key_from_env()
        return settings

    def load_api_key_from_env(self) -> str:
        env_path = Path(__file__).parent / '.env'
        if env_path.exists():
            env = dotenv.dotenv_values(str(env_path))
            return env.get('GEMINI_API_KEY', '')
        return ''

    def save_api_key_to_env(self, api_key: str):
        env_path = Path(__file__).parent / '.env'
        if not env_path.exists():
            env_path.touch()
        dotenv.set_key(str(env_path), 'GEMINI_API_KEY', api_key)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        settings_group = QGroupBox("Settings and API Keys")
        settings_layout = QFormLayout(settings_group)
        self.separate_settings_checkbox = QCheckBox("Use separate standalone settings")
        self.separate_settings_checkbox.setToolTip("When disabled, settings are shared with the Obsidian plugin.")
        self.separate_settings_checkbox.setChecked(self.use_separate_settings)
        self.separate_settings_checkbox.toggled.connect(self.toggle_settings_mode)
        settings_layout.addRow(self.separate_settings_checkbox)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        settings_layout.addRow("Gemini API Key (from .env):", self.api_key_input)

        self.model_input = QComboBox()
        self.model_input.setEditable(True)
        self.model_input.addItems(["gemini-2.0-flash-lite-preview-02-05", "gemini-1.5-flash", "gemini-1.5-pro"])
        settings_layout.addRow("Gemini model:", self.model_input)

        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("Optional instructions for Gemini during conversion...")
        self.prompt_input.setFixedHeight(70)
        settings_layout.addRow("Gemini prompt:", self.prompt_input)

        priority_widget = QWidget()
        priority_layout = QHBoxLayout(priority_widget)
        priority_layout.setContentsMargins(0, 0, 0, 0)
        self.priority_input = QComboBox()
        self.priority_input.addItems(["Gemini → Standard", "Standard → Gemini", "Gemini only", "Standard only"])
        priority_layout.addWidget(self.priority_input)
        settings_layout.addRow("Generator priority:", priority_widget)

        save_settings_button = QPushButton("Save settings")
        save_settings_button.clicked.connect(self.save_settings)
        settings_layout.addRow(save_settings_button)

        save_key_btn = QPushButton('Save API Key to .env')
        save_key_btn.clicked.connect(self.save_api_key_clicked)
        settings_layout.addRow(save_key_btn)

        layout.addWidget(settings_group)

        self.label = QLabel("Drag and drop a file here or select one")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("border: 2px dashed #aaa; padding: 20px;")
        layout.addWidget(self.label)

        select_btn = QPushButton("Select file")
        select_btn.clicked.connect(self.select_file)
        layout.addWidget(select_btn)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        layout.addWidget(self.output_text)

    def populate_settings_form(self):
        self.api_key_input.setText(self.load_api_key_from_env())
        self.model_input.setCurrentText(self.settings["modelName"])
        self.prompt_input.setPlainText(self.settings["promptOverride"])
        self.priority_input.setCurrentIndex(self.priority_to_index(self.settings["generatorPriority"]))

    @staticmethod
    def priority_to_index(priority: list[str]) -> int:
        return {("gemini", "standard"): 0, ("standard", "gemini"): 1, ("gemini",): 2, ("standard",): 3}.get(tuple(priority), 0)

    def selected_priority(self) -> list[str]:
        return [["gemini", "standard"], ["standard", "gemini"], ["gemini"], ["standard"]][self.priority_input.currentIndex()]

    def toggle_settings_mode(self, separate: bool):
        self.use_separate_settings = separate
        try:
            self.mode_path.write_text(json.dumps({"useSeparateSettings": separate}), encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(self, "Unable to save settings mode", str(error))
            return
        self.settings = self.load_settings()
        self.populate_settings_form()
        self.output_text.setText(f"Using {'separate standalone' if separate else 'shared'} settings.")

    def save_settings(self):
        # Do NOT save the API key in settings JSON
        s = dict(self.settings)
        s.pop('geminiApiKey', None)
        try:
            self.active_settings_path.write_text(json.dumps(s, indent=2), encoding='utf-8')
            self.engine = None
            self.output_text.setText(f"Settings saved to {self.active_settings_path.name} (except API Key; for that use the dedicated button).")
        except OSError as error:
            QMessageBox.critical(self, 'Unable to save settings', str(error))

    def save_api_key_clicked(self):
        api_key = self.api_key_input.text().strip()
        self.save_api_key_to_env(api_key)
        self.output_text.setText('API Key saved to .env file.')
        # Optionally update current settings too
        self.settings['geminiApiKey'] = api_key

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if file_path:
            self.process_file(file_path)

    def process_file(self, file_path):
        self.save_settings()
        self.engine = ConversionEngine(
            api_key=self.settings["geminiApiKey"],
            model_name=self.settings["modelName"],
            prompt_override=self.settings["promptOverride"],
            generator_priority=self.settings["generatorPriority"],
        )
        self.output_text.setText(f"Processing {file_path}...")
        QApplication.processEvents()
        self.output_text.setText(self.engine.convert(file_path))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MarkItDownApp()
    window.show()
    sys.exit(app.exec())
