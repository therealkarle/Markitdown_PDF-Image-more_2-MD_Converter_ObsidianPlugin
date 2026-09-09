import base64
from pathlib import Path

from engine.conversionEngine import materialize_embedded_images


PNG_BYTES = b"\x89PNG\r\n\x1a\nminimal-test-image"


def test_materializes_data_uri_and_keeps_external_link(tmp_path: Path) -> None:
    source = tmp_path / "WordTest.docx"
    source.write_bytes(b"input")
    data_uri = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
    markdown = f"[![Bild]({data_uri})](https://de.wikipedia.org/wiki/Lorem_ipsum)"

    result = materialize_embedded_images(markdown, source)

    assert "data:image/" not in result
    assert result.startswith("[![Bild](media/WordTest-image-001-")
    assert result.endswith(")](https://de.wikipedia.org/wiki/Lorem_ipsum)")
    image_path = next((tmp_path / "media").glob("WordTest-image-001-*.png"))
    assert image_path.read_bytes() == PNG_BYTES


def test_reuses_identical_embedded_images(tmp_path: Path) -> None:
    source = tmp_path / "document.docx"
    source.write_bytes(b"input")
    data_uri = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")

    result = materialize_embedded_images(f"![one]({data_uri})\n![two]({data_uri})", source)

    links = [line.split("](", 1)[1].rstrip(")") for line in result.splitlines()]
    assert links[0] == links[1]
    assert len(list((tmp_path / "media").glob("*.png"))) == 1

