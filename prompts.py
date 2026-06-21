from config import logger, settings
import jinja2

def get_prompt(filename: str, **kwargs) -> str:
    """Загружает промпт из файла и форматирует его."""
    filepath = settings.PROMPTS_DIR / filename
    if not filepath.exists():
        logger.error(f"Файл промпта не найден: {filepath}")
        raise FileNotFoundError(f"Prompt file {filename} not found.")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            template = file.read()
            
        if filename.endswith(".j2"):
            # Use Jinja2 for dynamic templates
            j2_env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
            return j2_env.from_string(template).render(**kwargs)
        else:
            # Fallback to standard Python string formatting
            if kwargs:
                return template.format(**kwargs)
            return template
            
    except Exception as e:
        logger.error(f"Ошибка чтения/форматирования промпта {filename}: {e}")
        raise