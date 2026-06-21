import json
import re
import httpx
import requests
from typing import Dict, Any, List
from config import settings, logger

class LiteLLMProvider:
    def __init__(self):
        self.api_url = settings.API_URL
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.LITELLM_USER_KEY}"
        }

    async def generate_multimodal(self, model_name: str, system_prompt: str, user_content: List[Dict[str, Any]], timeout_seconds: float = 600.0) -> Dict[Any, Any]:
        """Асинхронный вызов VLM модели с JSON форматом через LiteLLM шлюз."""
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.1,
            "max_tokens": 8192 if "gemma-4-31b" in model_name or "gemini" in model_name else 2000,
            "response_format": {"type": "json_object"}
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(self.api_url, json=payload, headers=self.headers)
                response.raise_for_status()
                result = response.json()
                raw_content = result['choices'][0]['message'].get('content')
                
                if raw_content is None:
                    logger.error(f"Модель {model_name} вернула None content. Полный ответ: {json.dumps(result)}")
                    return {"error": "null_content", "is_safe": False}
                
                return self._parse_json_robust(raw_content)

        except httpx.TimeoutException:
            logger.error(f"Таймаут запроса к модели {model_name}")
            return {"error": "timeout", "is_safe": False}
        except httpx.RequestError as e:
            logger.error(f"Сетевая ошибка при обращении к {model_name}: {e}")
            return {"error": "network_error", "is_safe": False}
        except Exception as e:
            logger.error(f"Непредвиденная ошибка в провайдере: {e}")
            return {"error": "internal_error", "is_safe": False}

    async def generate_embeddings(self, model_name: str, input_text: str) -> List[float]:
        """Генерирует векторные эмбеддинги через LiteLLM шлюз (асинхронно)."""
        payload = {
            "model": model_name,
            "input": input_text
        }
        try:
            url = f"{settings.LITELLM_API_BASE}/v1/embeddings"
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload, headers=self.headers)
                response.raise_for_status()
                result = response.json()
                return result['data'][0]['embedding']
        except Exception as e:
            logger.error(f"Ошибка при получении эмбеддингов для '{input_text}': {e}")
            # Возвращаем дефолтный нулевой вектор
            return [0.0] * 1024

    def _parse_json_robust(self, raw_content: str) -> Dict[Any, Any]:
        """Устойчивый парсер. Ищет JSON даже если модель добавила маркдаун."""
        try:
            return json.loads(raw_content)
        except json.JSONDecodeError:
            pass

        logger.debug("Прямой парсинг JSON не удался, применяю RegEx.")
        match = re.search(r'\{.*\}', raw_content, re.DOTALL)
        if match:
            clean_json_str = match.group(0)
            try:
                return json.loads(clean_json_str)
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка RegEx парсинга: {e}. Сырой ответ: {raw_content}")
                return {"error": "parse_error", "raw_content": raw_content}
        
        logger.error(f"Не удалось извлечь JSON. Ответ: {raw_content}")
        return {"error": "parse_error", "raw_content": raw_content}

llm_provider = LiteLLMProvider()