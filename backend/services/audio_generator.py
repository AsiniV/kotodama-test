"""
LocalAudioEngine — локальная генерация музыки (MusicGen) и звуковых эффектов
(AudioLDM 2) без внешних API. ЭТАП 2: Audio Pipeline.

Зависимости (устанавливаются в WSL2, см. Шаг 2.1):
    sudo apt update && sudo apt install -y ffmpeg libsndfile1
    pip install audiocraft transformers scipy torch

Модельный движок загружается ЛЕНИВО (в первом обращении), чтобы backend
стартовал нормально даже без аудио-зависимостей (например, в CI или на хосте,
где ещё не скачаны веса MusicGen/AudioLDM). Тяжёлые import-ы (torch,
audiocraft, transformers, scipy) вынесены внутрь методов.
"""

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("kotodama.services.audio")


class LocalAudioEngine:
    """Инкапсулирует загрузку моделей, генерацию и постобработку через FFmpeg."""

    def __init__(self):
        import torch  # local import: torch подтягивается только при создании движка

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"🔊 Audio Engine initializing on device: {self.device}")

        # MusicGen для музыки (medium - баланс качества и VRAM)
        from audiocraft.models import MusicGen

        self.MusicGen = MusicGen
        self.music_model = MusicGen.get_pretrained("facebook/musicgen-medium")

        # AudioLDM 2 для звуковых эффектов
        from transformers import pipeline

        self.sfx_pipeline = pipeline(
            "text-to-audio", model="cvssp/audioldm2", device=self.device
        )

    def generate_bgm(
        self,
        req_id: str,
        desc: str,
        duration: int,
        loop: bool,
        workspace_path: str,
    ) -> str:
        """Генерирует фоновую музыку; возвращает путь к итоговому .ogg файлу."""
        print(f"🎵 Generating BGM: {req_id}")
        self.music_model.set_generation_params(duration=duration)
        prompt = (
            f"high quality, seamless loop, video game soundtrack, {desc}, "
            "clear production, no sudden cuts"
        )

        wav = self.music_model.generate([prompt], progress=True)
        temp_path = Path(workspace_path) / f"temp_{req_id}.wav"
        final_path = Path(workspace_path) / f"{req_id}.ogg"  # Godot предпочитает OGG для музыки

        self.MusicGen.write_wav(wav, str(temp_path))

        # Постобработка FFmpeg: нормализация и кроссфейд для бесшовного лупа
        if loop:
            cmd = [
                "ffmpeg", "-y", "-i", str(temp_path),
                "-filter_complex",
                "[0:a]aloop=loop=0:size=2e+09,afade=t=out:st=0:d=0.5,afade=t=in:st=0:d=0.5[aout]",
                "-map", "[aout]", "-c:a", "libvorbis", "-q:a", "5", str(final_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", str(temp_path),
                "-c:a", "libvorbis", "-q:a", "5", str(final_path),
            ]

        subprocess.run(cmd, check=True, capture_output=True)
        os.remove(temp_path)
        return str(final_path)

    def generate_sfx(self, req_id: str, desc: str, workspace_path: str) -> str:
        """Генерирует звуковой эффект; возвращает путь к итоговому .wav файлу."""
        print(f"🔊 Generating SFX: {req_id}")
        import scipy.io.wavfile as wavfile

        prompt = f"sound effect, {desc}, isolated, clean, no background noise"
        result = self.sfx_pipeline(prompt, num_inference_steps=10)

        final_path = Path(workspace_path) / f"{req_id}.wav"  # Godot предпочитает WAV для коротких SFX
        wavfile.write(str(final_path), result["sampling_rate"], result["audio"][0])
        return str(final_path)


# ---------------------------------------------------------------------------
# Ленивый синглтон движка
# ---------------------------------------------------------------------------

_audio_engine: Optional[LocalAudioEngine] = None


def get_audio_engine() -> LocalAudioEngine:
    """Возвращает (лениво создавая) единственный экземпляр LocalAudioEngine.

    Поднимает RuntimeError с понятным сообщением, если аудио-зависимости
    (audiocraft / transformers / scipy / torch) не установлены.
    """
    global _audio_engine
    if _audio_engine is None:
        try:
            _audio_engine = LocalAudioEngine()
        except ImportError as e:
            raise RuntimeError(
                "Audio dependencies missing. Установи их в WSL2 (Шаг 2.1): "
                "sudo apt install -y ffmpeg libsndfile1 && "
                "pip install audiocraft transformers scipy torch"
            ) from e
    return _audio_engine


async def process_audio_task(
    req: Any,
    engine: LocalAudioEngine,
    workspace_path: str,
    game_id: str,
) -> Optional[str]:
    """Фоновая обработка одного AudioRequest (вызывается из FastAPI BackgroundTasks).

    req — объект схемы backend.schemas.agent_schemas.AudioRequest.
    Возвращает путь к готовому файлу либо None при ошибке.
    """
    try:
        if req.type == "bgm":
            file_path = await asyncio.to_thread(
                engine.generate_bgm,
                req.id,
                req.description,
                req.duration_sec,
                req.loop,
                workspace_path,
            )
        else:
            file_path = await asyncio.to_thread(
                engine.generate_sfx, req.id, req.description, workspace_path
            )

        # Загрузка результата в MinIO (kotodama-assets) — best effort:
        # при недоступном MinIO файл остаётся в workspace.
        try:
            from backend.services.minio_service import get_minio_service

            content_type = "audio/ogg" if req.type == "bgm" else "audio/wav"
            object_name = f"assets/{game_id}/audio/{Path(file_path).name}"
            uri = await get_minio_service().upload_asset(
                Path(file_path), object_name, content_type=content_type
            )
            logger.info(f"Audio {req.id} uploaded: {uri}")
        except Exception as me:  # noqa: BLE001
            logger.warning(f"MinIO upload skipped for {req.id}: {me}")

        # TODO: обновить статус задачи в БД/Redis, чтобы фронтенд узнал о готовности.

        print(f"✅ Audio {req.id} saved to {file_path}")
        return file_path
    except Exception as e:  # noqa: BLE001
        print(f"❌ Audio generation failed for {req.id}: {e}")
        return None
