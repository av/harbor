from collections.abc import AsyncGenerator
import logging
import time
from typing import Literal, Optional

from kokoro_onnx import Kokoro
import numpy as np

from speaches.audio import resample_audio

# Import our ONNX provider detection utility
try:
    from .onnx_utils import ONNXProviderDetector
    from .hf_utils import get_kokoro_model_path
except ImportError:
    try:
        # Fallback for when run directly
        from onnx_utils import ONNXProviderDetector
        from hf_utils import get_kokoro_model_path
    except ImportError:
        ONNXProviderDetector = None
        get_kokoro_model_path = None

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

def setup_kokoro_providers(onnx_providers: list[str] = None) -> dict:
    """
    Setup ONNX providers for Kokoro TTS with GPU acceleration.

    Args:
        onnx_providers: List of ONNX provider names. If None, auto-detects optimal providers.

    Returns:
        Dictionary with provider setup results including detected providers and performance info.
    """
    try:
        if onnx_providers is None:
            # Auto-detect optimal providers if not specified
            from onnx_utils import ONNXProviderDetector
            detector = ONNXProviderDetector()
            onnx_providers = detector.detect_optimal_providers()
            logger.info(f"Auto-detected ONNX providers for Kokoro: {onnx_providers}")

        # Setup environment for Kokoro with detected providers
        setup_result = {
            'providers': onnx_providers,
            'status': 'success',
            'gpu_available': any(provider in ['CUDAExecutionProvider', 'CoreMLExecutionProvider', 'DmlExecutionProvider'] for provider in onnx_providers)
        }

        logger.info(f"Kokoro providers setup completed: {setup_result}")
        return setup_result

    except Exception as e:
        logger.error(f"Failed to setup Kokoro providers: {e}")
        return {
            'providers': ['CPUExecutionProvider'],
            'status': 'fallback_cpu',
            'gpu_available': False,
            'error': str(e)
        }

def create_gpu_kokoro(model_path: str = None, providers: list[str] = None) -> Kokoro:
    """
    Create a GPU-accelerated Kokoro TTS instance.

    Args:
        model_path: Path to Kokoro model. If None, uses default from hf_utils.
        providers: ONNX providers to use. If None, auto-detects optimal providers.

    Returns:
        Configured Kokoro TTS instance with GPU acceleration if available.
    """
    try:
        # Get model path if not provided
        if model_path is None:
            from hf_utils import get_kokoro_model_path
            model_path = str(get_kokoro_model_path())
            logger.debug(f"Using default Kokoro model path: {model_path}")

        # Setup providers if not provided
        if providers is None:
            provider_setup = setup_kokoro_providers()
            providers = provider_setup['providers']

        # Create Kokoro instance with specified providers
        kokoro = Kokoro(providers=providers)
        logger.info(f"Created Kokoro TTS instance with providers: {providers}")

        return kokoro

    except Exception as e:
        logger.error(f"Failed to create GPU Kokoro instance: {e}")
        logger.info("Falling back to CPU-only Kokoro")

        # Fallback to CPU-only
        try:
            kokoro = Kokoro(providers=['CPUExecutionProvider'])
            logger.info("Created fallback CPU-only Kokoro TTS instance")
            return kokoro
        except Exception as fallback_error:
            logger.error(f"Even CPU fallback failed: {fallback_error}")
            raise

def test_kokoro_gpu_acceleration() -> dict:
    """
    Test Kokoro GPU acceleration and performance.

    Returns:
        Dictionary with test results including performance metrics and provider info.
    """
    test_results = {
        'gpu_test_passed': False,
        'cpu_test_passed': False,
        'providers_tested': [],
        'performance_metrics': {},
        'errors': []
    }

    try:
        # Test GPU acceleration
        logger.info("Testing Kokoro GPU acceleration...")

        # Setup providers
        provider_setup = setup_kokoro_providers()
        test_results['providers_tested'] = provider_setup['providers']

        if provider_setup['gpu_available']:
            try:
                # Create GPU instance
                kokoro_gpu = create_gpu_kokoro(providers=provider_setup['providers'])

                # Simple test text
                test_text = "Testing GPU acceleration"
                test_voice = "af_bella"

                # Measure performance
                start_time = time.perf_counter()

                # Run a quick synthesis test (sync version for testing)
                import asyncio

                async def run_test():
                    audio_chunks = []
                    async for chunk in generate_audio(kokoro_gpu, test_text, test_voice):
                        audio_chunks.append(chunk)
                    return b''.join(audio_chunks)

                audio_data = asyncio.run(run_test())
                end_time = time.perf_counter()

                if audio_data and len(audio_data) > 0:
                    test_results['gpu_test_passed'] = True
                    test_results['performance_metrics']['gpu_synthesis_time'] = end_time - start_time
                    test_results['performance_metrics']['audio_size_bytes'] = len(audio_data)
                    test_results['performance_metrics']['chars_per_second'] = len(test_text) / (end_time - start_time)

                    logger.info(f"GPU test passed: {test_results['performance_metrics']}")
                else:
                    test_results['errors'].append("GPU test produced no audio output")

            except Exception as gpu_error:
                test_results['errors'].append(f"GPU test failed: {gpu_error}")
                logger.warning(f"GPU acceleration test failed: {gpu_error}")

        # Test CPU fallback
        try:
            kokoro_cpu = create_gpu_kokoro(providers=['CPUExecutionProvider'])
            test_results['cpu_test_passed'] = True
            logger.info("CPU fallback test passed")
        except Exception as cpu_error:
            test_results['errors'].append(f"CPU test failed: {cpu_error}")
            logger.error(f"CPU fallback test failed: {cpu_error}")

    except Exception as e:
        test_results['errors'].append(f"Overall test failed: {e}")
        logger.error(f"Kokoro GPU acceleration test failed: {e}")

    return test_results

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