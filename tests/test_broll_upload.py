import pytest

from saas_uploads import validate_broll_upload, UploadValidationError


class TestValidateBrollUpload:
    def test_accepts_image(self):
        assert validate_broll_upload("image/png", 1_000_000) == ("image", "png")

    def test_accepts_video(self):
        assert validate_broll_upload("video/mp4", 5_000_000) == ("video", "mp4")

    def test_rejects_other_types(self):
        with pytest.raises(UploadValidationError) as e:
            validate_broll_upload("application/pdf", 100)
        assert e.value.status_code == 400

    def test_rejects_oversize_image(self):
        with pytest.raises(UploadValidationError) as e:
            validate_broll_upload("image/png", 26 * 1024 * 1024)
        assert e.value.status_code == 413

    def test_rejects_oversize_video(self):
        with pytest.raises(UploadValidationError) as e:
            validate_broll_upload("video/mp4", 101 * 1024 * 1024)
        assert e.value.status_code == 413
