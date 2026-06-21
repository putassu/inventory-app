import torch
import os
import uuid
import shutil
from transformers import AutoModel
from fastapi import FastAPI, UploadFile, File, HTTPException
import uvicorn

# Настройки
MODEL_ID = "ai-sage/GigaAM-v3"
REVISION = "e2e_rnnt"  # Лучшее качество с пунктуацией
DEVICE = "cuda"

app = FastAPI(title="GigaAM-v3 Professional ASR API")

print(f"🚀 Loading {MODEL_ID} ({REVISION}) to {DEVICE}...")

try:
    # Загружаем модель
    model = AutoModel.from_pretrained(
        MODEL_ID,
        revision=REVISION,
        trust_remote_code=True
    ).to(DEVICE)
    
    # Оптимизация для V100: переводим в float16
    # В README указано, что для HF-версии это делается так:
    model.model.encoder = model.model.encoder.half()
    
    model.eval()
    print("✅ Model loaded and optimized for V100 (fp16).")
except Exception as e:
    print(f"❌ Error loading model: {e}")
    raise

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    temp_path = f"temp_{uuid.uuid4()}_{file.filename}"
    
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        with torch.no_grad():
            result = model.transcribe(temp_path)
        
        # --- УНИВЕРСАЛЬНАЯ ОБРАБОТКА РЕЗУЛЬТАТА ---
        full_text = ""
        segments_data = []

        if isinstance(result, str):
            # Если вернулась одна строка
            full_text = result
            segments_data = [{"text": result}]
        
        elif isinstance(result, list):
            # Если вернулся список
            for item in result:
                if isinstance(item, str):
                    # Случай: ["строка1", "строка2"]
                    segments_data.append({"text": item})
                else:
                    # Случай: объекты с атрибутами .text, .start, .end
                    segments_data.append({
                        "text": getattr(item, 'text', str(item)),
                        "start": getattr(item, 'start', None),
                        "end": getattr(item, 'end', None)
                    })
            
            full_text = " ".join([s["text"] for s in segments_data])

        return {
            "text": full_text.strip(),
            "segments": segments_data,
            "status": "success"
        }

    except Exception as e:
        print(f"Inference error: {e}")
        # Выводим тип результата для отладки
        if 'result' in locals():
            print(f"Result type: {type(result)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == "__main__":
    # Запуск на порту 8007
    uvicorn.run(app, host="0.0.0.0", port=8007)
