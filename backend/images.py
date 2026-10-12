import hashlib
import struct
from pathlib import Path

from PIL import Image, ImageOps


EXTENSIONS = {'.jpg', '.jpeg', '.png'}


def fingerprint(path: Path):
    st = path.stat()
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


def decode(path: Path):
    with Image.open(path) as source:
        source.load()
        image = ImageOps.exif_transpose(source).convert('RGB')
    # Pixel hash ignores XMP/EXIF changes and merges identical decoded images.
    digest = hashlib.sha256(struct.pack('>II', *image.size) + image.tobytes()).hexdigest()
    return image, digest


def thumbnail(image, destination: Path):
    image = image.copy()
    image.thumbnail((640, 640))
    temp = destination.with_suffix('.tmp')
    image.save(temp, format='JPEG', quality=88)
    temp.replace(destination)
