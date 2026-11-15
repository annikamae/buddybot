from io import BytesIO

import pytest
from PIL import Image

from buddy_attachments import process_uploads, safe_filename


class UploadedFile:
    def __init__(self, name, data):
        self.name = name
        self.data = data

    def getvalue(self):
        return self.data


def test_text_file_is_extracted_and_filename_is_sanitized():
    text, images, names = process_uploads(
        [UploadedFile(r"..\secrets\review.py", b"print('hello')")]
    )

    assert "print('hello')" in text
    assert images == []
    assert names == ["review.py"]
    assert safe_filename("../../unsafe?.txt") == "unsafe_.txt"


def test_image_is_normalized_to_bounded_jpeg():
    image_bytes = BytesIO()
    Image.new("RGBA", (12, 8), (20, 40, 60, 120)).save(image_bytes, format="PNG")

    text, images, names = process_uploads(
        [UploadedFile("diagram.png", image_bytes.getvalue())]
    )

    assert text == ""
    assert names == ["diagram.png"]
    assert images[0]["mime"] == "image/jpeg"
    assert images[0]["data"]


def test_unsupported_upload_type_is_rejected():
    with pytest.raises(ValueError, match="not a supported"):
        process_uploads([UploadedFile("payload.exe", b"not executable")])


def test_oversized_file_is_rejected_before_parsing():
    with pytest.raises(ValueError, match="8 MiB"):
        process_uploads([UploadedFile("large.txt", b"x" * (8 * 1024 * 1024 + 1))])
