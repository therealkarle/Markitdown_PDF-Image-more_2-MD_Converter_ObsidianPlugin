from session_state import SessionFileState, format_conversion_error


def test_last_selected_file_remains_available_after_a_failed_conversion() -> None:
    state = SessionFileState()

    state.remember(r"C:\input\first.pdf")
    state.remember(r"C:\input\last.pdf")

    assert state.last_file_path == r"C:\input\last.pdf"
    assert state.has_file is True


def test_conversion_error_contains_file_name_and_reason() -> None:
    message = format_conversion_error(r"C:\input\last.pdf", RuntimeError("OCR unavailable"))

    assert message == "Error converting last.pdf: OCR unavailable"
