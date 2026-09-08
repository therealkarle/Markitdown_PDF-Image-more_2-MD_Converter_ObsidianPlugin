import sys
import os

# Add the repo root to sys.path so the shared engine package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QPushButton, QLabel, QFileDialog, QTextEdit, QLineEdit)
from PySide6.QtCore import Qt
from engine.conversionEngine import ConversionEngine
from dotenv import load_dotenv, set_key

class MarkItDownApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MarkItDown Pro Standalone")
        self.setMinimumSize(600, 400)
        
        self.env_path = os.path.join(os.path.dirname(__file__), ".env")
        load_dotenv(self.env_path)
        
        self.init_ui()
        self.engine = None

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # API Key Section
        layout.addWidget(QLabel("Gemini API Key:"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setText(os.getenv("GEMINI_API_KEY", ""))
        layout.addWidget(self.api_key_input)
        
        save_key_btn = QPushButton("Save API Key")
        save_key_btn.clicked.connect(self.save_api_key)
        layout.addWidget(save_key_btn)

        # Drag and Drop / File Selection
        self.label = QLabel("Drag and Drop a file here or click to select")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("border: 2px dashed #aaa; padding: 20px;")
        layout.addWidget(self.label)

        select_btn = QPushButton("Select File")
        select_btn.clicked.connect(self.select_file)
        layout.addWidget(select_btn)

        # Output Section
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        layout.addWidget(self.output_text)

    def save_api_key(self):
        api_key = self.api_key_input.text()
        if not os.path.exists(self.env_path):
            with open(self.env_path, "w") as f:
                f.write("")
        set_key(self.env_path, "GEMINI_API_KEY", api_key)
        self.engine = ConversionEngine(api_key)
        self.output_text.setText("API Key saved and engine reloaded.")

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if file_path:
            self.process_file(file_path)

    def process_file(self, file_path):
        if not self.engine:
            self.engine = ConversionEngine(self.api_key_input.text())
        
        self.output_text.setText(f"Processing {file_path}...")
        QApplication.processEvents()
        
        result = self.engine.convert(file_path)
        self.output_text.setText(result)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MarkItDownApp()
    window.show()
    sys.exit(app.exec())
