import base64
from pathlib import Path
from PIL import Image
from config import settings, logger

def optimize_image(input_path: Path, total_images: int = 1) -> Path:
    """
    Сжимает изображение с сохранением деталей (Lanczos).
    Размер зависит от общего количества отправляемых картинок.
    """
    # Ограничиваем ключ словаря максимумом в 3
    target_size = settings.ADAPTIVE_IMAGE_SIZES.get(min(total_images, 3), 512)
    output_path = input_path.with_name(f"{input_path.stem}_opt_{target_size}.jpg")
    
    try:
        with Image.open(input_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            img.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
            img.save(output_path, "JPEG", quality=settings.JPEG_QUALITY, optimize=True)
            logger.debug(f"Изображение адаптировано под {total_images} шт. ({target_size}px): {output_path.name}")
            
        return output_path
    except Exception as e:
        logger.error(f"Ошибка при оптимизации {input_path.name}: {e}")
        return None

def generate_thumbnail(input_path: Path) -> Path:
    """
    Генерирует легковесное превью 256x256 для списков на клиенте (Android).
    """
    output_path = input_path.with_name(f"{input_path.stem}_thumb.jpg")
    
    try:
        with Image.open(input_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # Для превью можно использовать более быстрый фильтр BICUBIC
            img.thumbnail((settings.THUMBNAIL_SIZE, settings.THUMBNAIL_SIZE), Image.Resampling.BICUBIC)
            img.save(output_path, "JPEG", quality=settings.THUMBNAIL_QUALITY, optimize=True)
            logger.debug(f"Превью создано: {output_path.name}")
            
        return output_path
    except Exception as e:
        logger.error(f"Ошибка при создании превью для {input_path.name}: {e}")
        return None

def encode_file_base64(file_path: Path) -> str:
    """Кодирует любой файл в Base64 для отправки в API."""
    try:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Ошибка кодирования файла {file_path.name}: {e}")
        return None

def create_vertical_collage(input_paths: list[Path], target_width: int) -> Path:
    """
    Склеивает несколько изображений вертикально в одно длинное.
    Это обходит баг llama.cpp с n_chunks > 1, сохраняя качество текста.
    """
    if not input_paths:
        return None
        
    images = []
    total_height = 0
    
    # Открываем и масштабируем каждую картинку под единую ширину
    for path in input_paths:
        try:
            img = Image.open(path)
            if img.mode != "RGB":
                img = img.convert("RGB")
                
            # Вычисляем пропорциональную высоту
            aspect_ratio = img.height / img.width
            new_height = int(target_width * aspect_ratio)
            
            img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
            images.append(img)
            total_height += new_height
        except Exception as e:
            logger.error(f"Ошибка чтения фото для коллажа {path.name}: {e}")
            
    if not images:
        return None

    # Создаем пустой холст нужного размера
    collage = Image.new('RGB', (target_width, total_height))
    
    # Вставляем картинки друг под другом
    current_y = 0
    for img in images:
        collage.paste(img, (0, current_y))
        current_y += img.height
        img.close()
        
    # Сохраняем результат
    output_path = input_paths[0].with_name(f"{input_paths[0].stem}_collage.jpg")
    collage.save(output_path, "JPEG", quality=settings.JPEG_QUALITY, optimize=True)
    logger.debug(f"Создан вертикальный коллаж: {output_path.name}")
    
    return output_path