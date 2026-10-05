"""Background removal via existing rembg — do not duplicate model logic."""

from __future__ import annotations


def _remove(data: bytes) -> bytes:
    from rembg import remove

    return remove(data)


def remove_png_to_path(input_path: str, output_path: str, method: str = "rembg") -> None:
    if method == "remove_white":
        from PIL import Image
        img = Image.open(input_path).convert("RGBA")
        datas = img.getdata()
        new_data = []
        for item in datas:
            if item[0] >= 235 and item[1] >= 235 and item[2] >= 235:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append(item)
        img.putdata(new_data)
        img.save(output_path, "PNG")
    elif method == "remove_black":
        from PIL import Image
        img = Image.open(input_path).convert("RGBA")
        datas = img.getdata()
        new_data = []
        for item in datas:
            if item[0] <= 20 and item[1] <= 20 and item[2] <= 20:
                new_data.append((0, 0, 0, 0))
            else:
                new_data.append(item)
        img.putdata(new_data)
        img.save(output_path, "PNG")
    else:
        with open(input_path, "rb") as f:
            data = _remove(f.read())
        with open(output_path, "wb") as wf:
            wf.write(data)


def remove_bytes(data: bytes) -> bytes:
    return _remove(data)
