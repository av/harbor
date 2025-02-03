from collections.abc import AsyncGenerator
import logging
import time
from typing import Literal

from kokoro_onnx import Kokoro
import numpy as np

from speaches.audio import resample_audio

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24000  # the default sample rate for Kokoro
Language = Literal["en-us", "en-gb", "fr-fr", "ja", "ko", "cmn"]
LANGUAGES: list[Language] = ["en-us", "en-gb", "fr-fr", "ja", "ko", "cmn"]

# TODO: delete when officially supports Kokoro v1
VOICE_IDS = [
    'af_heart',
    'af_alloy', 'af_aoede', 'af_bella', 'af_jessica', 'af_kore', 'af_nicole',
    'af_nova', 'af_river', 'af_sarah', 'af_sky', 'am_adam', 'am_echo',
    'am_eric', 'am_fenrir', 'am_liam', 'am_michael', 'am_onyx', 'am_puck',
    'bf_alice', 'bf_emma', 'bf_isabella', 'bf_lily', 'bm_daniel', 'bm_fable',
    'bm_george', 'bm_lewis', 'ff_siwis', 'if_sara', 'im_nicola', 'jf_alpha',
    'jf_gongitsune', 'jf_nezumi', 'jf_tebukuro', 'jm_kumo', 'zf_xiaobei',
    'zf_xiaoni', 'zf_xiaoxiao', 'zf_xiaoyi', 'zm_yunjian', 'zm_yunxi',
    'zm_yunxia', 'zm_yunyang'
]

async def generate_audio(
    kokoro_tts: Kokoro,
    text: str,
    voice: str,
    *,
    language: Language = "en-us",
    speed: float = 1.0,
    sample_rate: int | None = None,
) -> AsyncGenerator[bytes, None]:
    if sample_rate is None:
        sample_rate = SAMPLE_RATE
    start = time.perf_counter()
    async for audio_data, _ in kokoro_tts.create_stream(text, voice, lang=language, speed=speed):
        assert isinstance(audio_data, np.ndarray) and audio_data.dtype == np.float32 and isinstance(sample_rate, int)
        normalized_audio_data = (audio_data * np.iinfo(np.int16).max).astype(np.int16)
        audio_bytes = normalized_audio_data.tobytes()
        if sample_rate != SAMPLE_RATE:
            audio_bytes = resample_audio(audio_bytes, SAMPLE_RATE, sample_rate)
        yield audio_bytes
    logger.info(f"Generated audio for {len(text)} characters in {time.perf_counter() - start}s")