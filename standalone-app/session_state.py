"""Session-only state for the standalone converter UI."""

from pathlib import Path


class SessionFileState:
    """Keep the most recently selected file available during one app run."""

    def __init__(self) -> None:
        self.last_file_path: str | None = None

    def remember(self, file_path: str) -> str:
        self.last_file_path = str(Path(file_path))
        return self.last_file_path

    @property
    def has_file(self) -> bool:
        return self.last_file_path is not None


def format_conversion_error(file_path: str, error: object) -> str:
    """Return a concise user-facing error while retaining the original reason."""

    message = str(error).strip() or error.__class__.__name__
    return f"Error converting {Path(file_path).name}: {message}"
