"""
Shared utilities for the clients app.

Contains photo validation helpers used by both the client portal views
and the owner portal admin views when handling image uploads.
"""
import os


_ALLOWED_PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB cap on all uploaded photos/posters


def validate_photo(photo):
    """Validate an uploaded image file.

    Checks file size, extension, and uses Pillow to verify the image data
    is not corrupt or spoofed.

    Args:
        photo: An InMemoryUploadedFile or TemporaryUploadedFile from request.FILES.

    Returns:
        str: An error message if invalid, or None if the photo passes all checks.
    """
    if photo.size > _MAX_PHOTO_BYTES:
        return 'Photo must be under 5 MB.'
    ext = os.path.splitext(photo.name)[1].lower()
    if ext not in _ALLOWED_PHOTO_EXTENSIONS:
        return 'Only JPG, PNG, and WebP images are allowed.'
    try:
        from PIL import Image
        img = Image.open(photo)
        img.verify()   # raises if file is corrupt or not a real image
        photo.seek(0)  # reset stream position after verify() exhausts it
    except Exception:
        return 'Uploaded file is not a valid image.'
    return None


# Keep legacy underscore-prefixed alias so existing call-sites don't break
_validate_photo = validate_photo
