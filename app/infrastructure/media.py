import hashlib
import io
import math
import wave
from contextlib import contextmanager

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from app.domain.common import digest
from app.domain.errors import DomainError, require

IMAGE_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


@contextmanager
def checked_image(data, max_pixels):
    try:
        with Image.open(io.BytesIO(data)) as source:
            require(
                source.format in IMAGE_TYPES,
                "UNSUPPORTED_MEDIA_TYPE",
                "Поддерживаются JPEG, PNG и WebP.",
                415,
            )
            require(
                source.width * source.height <= max_pixels,
                "DECODED_IMAGE_TOO_LARGE",
                "Слишком много пикселей в изображении.",
                413,
            )
            require(
                getattr(source, "n_frames", 1) == 1,
                "UNSUPPORTED_MEDIA_TYPE",
                "Анимация не поддерживается.",
                415,
            )
            yield source
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", "Файл не является безопасным изображением.", 415) from exc


def decode_image(data, max_pixels, max_side=None):
    with checked_image(data, max_pixels) as source:
        mime = IMAGE_TYPES[source.format]
        # JPEG уменьшается декодером до загрузки пикселей; поворот выполняется уже на малой копии.
        if max_side:
            ratio = min(max_side / max(source.size), 1)
            source.draft("RGB", tuple(max(1, round(side * ratio)) for side in source.size))
            source.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        ImageOps.exif_transpose(source, in_place=True)
        if source.has_transparency_data:
            rgba = source.convert("RGBA")
            image = Image.new("RGB", source.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = source.convert("RGB")
        image.info.clear()
        return image, mime


def inspect_media(data, declared_mime, settings):
    require(len(data) <= settings["media.max_file_bytes"], "FILE_TOO_LARGE", "Файл превышает лимит.", 413)
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        try:
            with wave.open(io.BytesIO(data)) as audio:
                require(
                    audio.getcomptype() == "NONE"
                    and audio.getsampwidth() == 2
                    and audio.getnchannels() in {1, 2},
                    "UNSUPPORTED_MEDIA_TYPE",
                    "Нужна запись WAV PCM 16 bit, один или два канала.",
                    415,
                )
                duration = audio.getnframes() / audio.getframerate()
                require(
                    0 < duration <= settings["media.max_audio_seconds"],
                    "AUDIO_TOO_LONG",
                    "Запись превышает допустимую длительность.",
                    413,
                )
                require(
                    declared_mime in {"audio/wav", "audio/x-wav", "audio/wave"},
                    "UNSUPPORTED_MEDIA_TYPE",
                    "MIME не соответствует WAV.",
                    415,
                )
                return {"mime": "audio/wav", "duration_seconds": str(duration), "width": None, "height": None}
        except (wave.Error, EOFError, ZeroDivisionError) as exc:
            raise DomainError("UNSUPPORTED_MEDIA_TYPE", "Повреждённая запись WAV.", 415) from exc
    with checked_image(data, settings["media.max_decoded_pixels"]) as source:
        mime = IMAGE_TYPES[source.format]
        require(
            declared_mime == mime,
            "UNSUPPORTED_MEDIA_TYPE",
            "MIME не соответствует содержимому изображения.",
            415,
        )
        # API проверяет контейнер и записывает размеры исходника; пиксели и EXIF обрабатывает CPU worker.
        source.verify()
        return {"mime": mime, "width": source.width, "height": source.height, "duration_seconds": None}


def jpeg(image, quality=80):
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()


def bounded_jpeg(image, quality=80, max_bytes=262144):
    """Сжатие не меняет координаты manifest и не отправляет слишком большой payload."""
    for current in range(quality, 29, -10):
        payload = jpeg(image, current)
        if len(payload) <= max_bytes:
            return payload
    raise DomainError("MODEL_IMAGE_LIMIT", "Изображение не помещается в безопасный лимит модели.", 413)


def build_collage(sources, settings, config_revision=1):
    require(sources, "NO_IMAGES", "Для коллажа нужны изображения.", 422)
    # Сетка строится по размерам с учётом поворота, без полноразмерных RGB-копий.
    sizes = []
    for _, data in sources:
        with checked_image(data, settings["media.max_decoded_pixels"]) as source:
            rotated = source.getexif().get(274) in {5, 6, 7, 8}
            sizes.append(source.size[::-1] if rotated else source.size)
    width, height = settings["collage.max_width"], settings["collage.max_height"]
    quality = settings.get("media.jpeg_quality", 80)
    max_bytes = settings.get("model.image_max_bytes", 262144)
    if len(sources) == 1:
        # Одному снимку не нужны сетка, поля и подпись: сохраняем полезные пиксели.
        image = decode_image(sources[0][1], settings["media.max_decoded_pixels"], max(width, height))[0]
        original_width, original_height = sizes[0]
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        rect = {"x": 0, "y": 0, "width": image.width, "height": image.height}
        manifest = {
            "schema_version": "collage.v1",
            "canvas_width": image.width,
            "canvas_height": image.height,
            "preprocessing_version": "collage-3",
            "config_revision": config_revision,
            "tiles": [
                {
                    "index": 1,
                    "media_id": sources[0][0],
                    "rect": rect,
                    "content_rect": rect,
                    "normalized_source_width": original_width,
                    "normalized_source_height": original_height,
                    "scale": image.width / original_width,
                    "small_tile": min(image.size) < settings["collage.min_tile_side"],
                }
            ],
        }
        manifest["cache_key"] = digest(
            {"source": hashlib.sha256(sources[0][1]).hexdigest(), "manifest": manifest, "quality": quality}
        )
        return bounded_jpeg(image, quality, max_bytes), manifest
    strip, padding = 30, 8
    grids = [(cols, math.ceil(len(sizes) / cols)) for cols in range(1, len(sizes) + 1)]

    def coverage(grid):
        cols, rows = grid
        cell_w, cell_h = width // cols - 2 * padding, height // rows - strip - 2 * padding
        return sum(w * h * min(cell_w / w, cell_h / h, 1) ** 2 for w, h in sizes)

    cols, rows = max(grids, key=coverage)
    canvas = Image.new("RGB", (width, height), "#f1f2f4")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    tiles = []
    for i, (media_id, data) in enumerate(sources):
        image = decode_image(data, settings["media.max_decoded_pixels"], max(width, height))[0]
        original_width, original_height = sizes[i]
        x, y = (i % cols) * (width // cols), (i // cols) * (height // rows)
        cell_w, cell_h = width // cols, height // rows
        scale = min(
            (cell_w - 2 * padding) / original_width, (cell_h - strip - 2 * padding) / original_height, 1
        )
        size = (max(1, round(original_width * scale)), max(1, round(original_height * scale)))
        thumb = image.resize(size, Image.Resampling.LANCZOS)
        cx, cy = x + (cell_w - size[0]) // 2, y + strip + (cell_h - strip - size[1]) // 2
        canvas.paste(thumb, (cx, cy))
        draw.text((x + padding, y + 4), f"Фото {i + 1}", fill="#111111", font=font)
        tiles.append(
            {
                "index": i + 1,
                "media_id": media_id,
                "rect": {"x": x, "y": y + strip, "width": cell_w, "height": cell_h - strip},
                "content_rect": {"x": cx, "y": cy, "width": size[0], "height": size[1]},
                "normalized_source_width": original_width,
                "normalized_source_height": original_height,
                "scale": scale,
                "small_tile": min(size) < settings["collage.min_tile_side"],
            }
        )
    manifest = {
        "schema_version": "collage.v1",
        "canvas_width": width,
        "canvas_height": height,
        "preprocessing_version": "collage-3",
        "config_revision": config_revision,
        "tiles": tiles,
    }
    manifest["cache_key"] = digest(
        {
            "sources": [(mid, hashlib.sha256(data).hexdigest()) for mid, data in sources],
            "manifest": manifest,
            "quality": quality,
        }
    )
    return bounded_jpeg(canvas, quality, max_bytes), manifest


def source_region(manifest, rectangle):
    x, y, w, h = rectangle
    for tile in manifest["tiles"]:
        c = tile["content_rect"]
        if (
            c["x"] <= x
            and c["y"] <= y
            and x + w <= c["x"] + c["width"]
            and y + h <= c["y"] + c["height"]
            and w > 0
            and h > 0
        ):
            return {
                "media_id": tile["media_id"],
                "x": (x - c["x"]) / c["width"],
                "y": (y - c["y"]) / c["height"],
                "width": w / c["width"],
                "height": h / c["height"],
            }
    raise DomainError("INVALID_IMAGE_REGION", "Область пересекает подпись, поля или разные фотографии.", 422)


def crop_source(data, region, max_pixels):
    image, _ = decode_image(data, max_pixels)
    x, y, w, h = (region[k] for k in ("x", "y", "width", "height"))
    require(
        0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0 and x + w <= 1 and y + h <= 1,
        "INVALID_IMAGE_REGION",
        "Неверные координаты фрагмента.",
        422,
    )
    return jpeg(
        image.crop(
            (
                round(x * image.width),
                round(y * image.height),
                round((x + w) * image.width),
                round((y + h) * image.height),
            )
        )
    )
