"""Read and validate the binary PPM captures used by renderer diagnostics."""

from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class PpmImage:
    width: int
    height: int
    pixels: bytes
    sha256: str


def read_ppm(path):
    data = path.read_bytes()
    position = 0

    def token():
        nonlocal position
        while position < len(data):
            if data[position] == ord("#"):
                newline = data.find(b"\n", position)
                if newline < 0:
                    raise ValueError(f"{path}: unterminated PPM comment")
                position = newline + 1
            elif data[position] in b" \t\r\n":
                position += 1
            else:
                break
        start = position
        while (
            position < len(data)
            and data[position] not in b" \t\r\n"
            and data[position] != ord("#")
        ):
            position += 1
        if start == position:
            raise ValueError(f"{path}: incomplete PPM header")
        return data[start:position]

    if token() != b"P6":
        raise ValueError(f"{path}: expected a binary P6 PPM")
    try:
        width = int(token())
        height = int(token())
        maximum = int(token())
    except ValueError as error:
        raise ValueError(f"{path}: invalid PPM header") from error
    if maximum != 255 or width < 1 or height < 1:
        raise ValueError(f"{path}: unsupported PPM dimensions or range")
    if data[position:position + 2] == b"\r\n":
        position += 2
    elif position < len(data) and data[position] in b" \t\r\n":
        position += 1
    else:
        raise ValueError(f"{path}: missing PPM pixel separator")
    pixels = data[position:]
    if len(pixels) != width * height * 3:
        raise ValueError(f"{path}: truncated or oversized PPM pixels")
    return PpmImage(width, height, pixels, hashlib.sha256(data).hexdigest())


def validate_region(region, width, height):
    if len(region) != 4:
        raise ValueError("frame_region must contain x, y, width, height")
    x, y, region_width, region_height = region
    if (
        x < 0
        or y < 0
        or region_width < 1
        or region_height < 1
        or x + region_width > width
        or y + region_height > height
    ):
        raise ValueError(
            f"frame_region {region} is outside {width}x{height}"
        )
    return x, y, region_width, region_height
