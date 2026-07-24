"""Pure, framework-free validation helpers for SaaSShorts user uploads.

Kept out of app.py so the validation logic is unit-testable without importing
FastAPI (CI installs only light deps). The endpoint translates
UploadValidationError into an HTTPException.
"""

BROLL_IMAGE_MAX_BYTES = 25 * 1024 * 1024
BROLL_VIDEO_MAX_BYTES = 100 * 1024 * 1024

_BROLL_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}


class UploadValidationError(Exception):
    """Carries an HTTP-ish status code so the endpoint can re-raise faithfully."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def validate_broll_upload(content_type: str, size: int):
    """Validate a b-roll upload's type and size; return (kind, ext) or raise."""
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        kind, cap = "image", BROLL_IMAGE_MAX_BYTES
    elif ct.startswith("video/"):
        kind, cap = "video", BROLL_VIDEO_MAX_BYTES
    else:
        raise UploadValidationError(400, "File must be an image or video")
    if size > cap:
        raise UploadValidationError(413, f"{kind.title()} too large")
    ext = _BROLL_EXT.get(ct, "png" if kind == "image" else "mp4")
    return kind, ext
