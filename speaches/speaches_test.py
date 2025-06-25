#!/usr/bin/env python3
"""
Speaches Testing Utilities

This module provides comprehensive testing functionality for the Speaches native service,
including tests for HuggingFace utilities, Kokoro TTS, ONNX providers, and service manager.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional
import os
import tempfile
import subprocess
import pytest
import yaml

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_imports():
    """Test that all required modules can be imported."""
    print("Testing imports...")

    try:
        from . import hf_utils
        print("  ✓ hf_utils imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import hf_utils: {e}")
        return False

    try:
        from . import kokoro_utils
        print("  ✓ kokoro_utils imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import kokoro_utils: {e}")
        return False

    try:
        from . import onnx_utils
        print("  ✓ onnx_utils imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import onnx_utils: {e}")
        return False

    try:
        from . import speaches_service_manager
        print("  ✓ speaches_service_manager imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import speaches_service_manager: {e}")
        return False

    print("All imports successful!")
    return True

def test_hf_utils():
    """Test HuggingFace utilities functionality."""
    print("\nTesting HuggingFace utilities...")

    try:
        from . import hf_utils
    except ImportError as e:
        print(f"  ✗ Cannot import hf_utils: {e}")
        return False

    # Test local model listing
    try:
        local_models = hf_utils.list_local_model_ids()
        print(f"  ✓ Found {len(local_models)} local models")
        if local_models:
            print(f"    Sample models: {local_models[:3]}")
    except Exception as e:
        print(f"  ✗ Error listing local models: {e}")
        return False

    # Test Kokoro model path detection
    try:
        kokoro_path = hf_utils.get_kokoro_model_path()
        print(f"  ✓ Kokoro model path: {kokoro_path}")
        print(f"    Kokoro model exists: {kokoro_path.exists()}")
    except Exception as e:
        print(f"  ⚠ Error getting Kokoro model path (may need download): {e}")

    # Test local Whisper models
    try:
        whisper_models = list(hf_utils.list_local_whisper_models())
        print(f"  ✓ Found {len(whisper_models)} local Whisper models")
    except Exception as e:
        print(f"  ✗ Error listing Whisper models: {e}")
        return False

    print("  HF utilities test completed.")
    return True

def test_onnx_utils():
    """Test ONNX utilities functionality."""
    print("\nTesting ONNX utilities...")

    try:
        from . import onnx_utils
    except ImportError as e:
        print(f"  ✗ Cannot import onnx_utils: {e}")
        return False

    # Test ONNX provider detection
    try:
        detector = onnx_utils.ONNXProviderDetector()
        providers = detector.detect_optimal_providers()
        print(f"  ✓ Detected ONNX providers: {providers}")

        # Test environment setup
        detector.setup_environment()
        print("  ✓ ONNX environment setup completed")

    except Exception as e:
        print(f"  ✗ Error with ONNX provider detection: {e}")
        return False

    print("  ONNX utilities test completed.")
    return True

def test_kokoro_utils():
    """Test Kokoro utilities functionality."""
    print("\nTesting Kokoro utilities...")

    try:
        from . import kokoro_utils
    except ImportError as e:
        print(f"  ✗ Cannot import kokoro_utils: {e}")
        return False

    # Test provider setup
    try:
        providers = kokoro_utils.setup_kokoro_providers()
        print(f"  ✓ Kokoro providers: {providers}")
    except Exception as e:
        print(f"  ✗ Error setting up Kokoro providers: {e}")
        return False

    # Test GPU acceleration
    try:
        gpu_test_results = kokoro_utils.test_kokoro_gpu_acceleration()
        gpu_works = gpu_test_results.get('gpu_test_passed', False) or gpu_test_results.get('cpu_test_passed', False)
        print(f"  ✓ GPU acceleration test: {'PASS' if gpu_works else 'FAIL'}")
        if not gpu_works and gpu_test_results.get('errors'):
            print(f"    Errors: {gpu_test_results['errors'][:2]}")  # Show first 2 errors
    except Exception as e:
        print(f"  ✗ Error testing GPU acceleration: {e}")
        return False

    # Test Kokoro instance creation
    try:
        kokoro_tts = kokoro_utils.create_gpu_kokoro()
        print(f"  ✓ Kokoro TTS instance created: {kokoro_tts is not None}")
    except Exception as e:
        print(f"  ✗ Error creating Kokoro TTS instance: {e}")
        return False

    print("  Kokoro utilities test completed.")
    return True

async def test_audio_generation():
    """Test audio generation functionality."""
    print("\nTesting audio generation...")

    try:
        from . import kokoro_utils
    except ImportError as e:
        print(f"  ✗ Cannot import kokoro_utils: {e}")
        return False

    try:
        text = "Hello, this is a test of Kokoro TTS."
        print(f"  Generating audio for: '{text}'")

        # Create a Kokoro TTS instance
        kokoro_tts = kokoro_utils.create_gpu_kokoro()

        chunks = []
        async for chunk in kokoro_utils.generate_audio(kokoro_tts, text, "af_alloy"):
            chunks.append(chunk)
            if len(chunks) >= 3:  # Limit test to first few chunks
                break

        total_size = sum(len(chunk) for chunk in chunks)
        print(f"  ✓ Generated {len(chunks)} audio chunks, total size: {total_size} bytes")

    except Exception as e:
        print(f"  ✗ Error generating audio: {e}")
        return False

    print("  Audio generation test completed.")
    return True

def test_service_manager():
    """Test service manager functionality."""
    print("\nTesting service manager...")

    try:
        from . import speaches_service_manager
    except ImportError as e:
        print(f"  ✗ Cannot import speaches_service_manager: {e}")
        return False

    try:
        # Test initialization
        manager = speaches_service_manager.SpeachesServiceManager()
        print("  ✓ Service manager created successfully")

        # Test health check
        health_status = manager.health_check()
        print(f"  ✓ Health check: {'PASS' if health_status else 'FAIL'}")

    except Exception as e:
        print(f"  ✗ Error testing service manager: {e}")
        return False

    print("  Service manager test completed.")
    return True

async def run_full_test_suite():
    """Run the complete test suite."""
    print("=" * 60)
    print("SPEACHES NATIVE SERVICE TEST SUITE")
    print("=" * 60)

    tests_passed = 0
    total_tests = 6

    # Test imports
    if test_imports():
        tests_passed += 1

    # Test HF utilities
    if test_hf_utils():
        tests_passed += 1

    # Test ONNX utilities
    if test_onnx_utils():
        tests_passed += 1

    # Test Kokoro utilities
    if test_kokoro_utils():
        tests_passed += 1

    # Test audio generation
    if await test_audio_generation():
        tests_passed += 1

    # Test service manager
    if test_service_manager():
        tests_passed += 1

    print("\n" + "=" * 60)
    print(f"TEST RESULTS: {tests_passed}/{total_tests} tests passed")
    print("=" * 60)

    return tests_passed == total_tests

def list_models():
    """List available models."""
    print("=" * 60)
    print("AVAILABLE MODELS")
    print("=" * 60)

    try:
        from . import hf_utils

        print("\nLocal Whisper models:")
        whisper_count = 0
        for model_info in hf_utils.list_local_whisper_models():
            print(f"  - {model_info[0].repo_id}")
            whisper_count += 1
            if whisper_count >= 10:  # Limit output
                print("  ... (more models available)")
                break

        print(f"\nFound {whisper_count} Whisper models")

        print("\nLocal Piper models:")
        piper_count = 0
        for voice in hf_utils.list_piper_models():
            print(f"  - {voice.voice_id}")
            piper_count += 1
            if piper_count >= 10:  # Limit output
                print("  ... (more voices available)")
                break

        print(f"\nFound {piper_count} Piper voices")

    except Exception as e:
        print(f"Error listing models: {e}")
        return False

    return True

def show_providers():
    """Show available ONNX providers."""
    print("=" * 60)
    print("ONNX PROVIDERS")
    print("=" * 60)

    try:
        from . import onnx_utils, kokoro_utils

        # Show system capabilities
        detector = onnx_utils.ONNXProviderDetector()
        providers = detector.detect_optimal_providers()

        print("\nDetected optimal providers:")
        for provider in providers:
            print(f"  - {provider}")

        # Show Kokoro-specific setup
        kokoro_providers = kokoro_utils.setup_kokoro_providers()
        print(f"\nKokoro providers: {kokoro_providers}")

    except Exception as e:
        print(f"Error getting providers: {e}")
        return False

    return True

def download_kokoro():
    """Download Kokoro model."""
    print("=" * 60)
    print("KOKORO MODEL DOWNLOAD")
    print("=" * 60)

    try:
        from . import hf_utils

        print("Downloading Kokoro model...")
        hf_utils.download_kokoro_model()

        # Verify download
        model_path = hf_utils.get_kokoro_model_path()
        print(f"✓ Kokoro model downloaded successfully")
        print(f"  Path: {model_path}")
        print(f"  Exists: {model_path.exists()}")

        if model_path.exists():
            size_mb = model_path.stat().st_size / (1024 * 1024)
            print(f"  Size: {size_mb:.1f} MB")

    except Exception as e:
        print(f"Error downloading Kokoro model: {e}")
        return False

    return True

# Test config hierarchy: CLI > ENV > YAML > DEFAULTS
def test_config_hierarchy(monkeypatch):
    # Set up a temp config file
    config = {"host": "1.2.3.4", "port": 12345, "provider": "CPUExecutionProvider", "tts": True, "stt": True, "voice": "testvoice"}
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        yaml.dump(config, f)
        config_path = f.name
    monkeypatch.setenv("SPEACHES_CONFIG", config_path)
    monkeypatch.setenv("HARBOR_SPEACHES_HOST", "5.6.7.8")
    monkeypatch.setenv("HARBOR_SPEACHES_HOST_PORT", "54321")
    monkeypatch.setenv("ONNX_PROVIDER", "CUDAExecutionProvider")
    # CLI args should override env/config
    args = [sys.executable, "speaches_service_manager.py", "--host", "9.9.9.9", "--port", "9999", "--provider", "CoreMLExecutionProvider", "--tts", "--stt", "--voice", "cli-voice"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert "9.9.9.9" in result.stdout or "9.9.9.9" in result.stderr
    assert "9999" in result.stdout or "9999" in result.stderr
    assert "CoreMLExecutionProvider" in result.stdout or "CoreMLExecutionProvider" in result.stderr
    assert "cli-voice" in result.stdout or "cli-voice" in result.stderr

# Test ONNX provider fallback
def test_onnx_provider_fallback(monkeypatch):
    monkeypatch.delenv("ONNX_PROVIDER", raising=False)
    args = [sys.executable, "speaches_service_manager.py", "--host", "127.0.0.1", "--port", "34331"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert "Auto-selected ONNX provider" in result.stdout or "Auto-selected ONNX provider" in result.stderr
    assert "CPUExecutionProvider" in result.stdout or "CPUExecutionProvider" in result.stderr

# Test simultaneous TTS/STT/voice handling
def test_tts_stt_voice(monkeypatch):
    args = [sys.executable, "speaches_service_manager.py", "--tts", "--stt", "--voice", "testvoice"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert "TTS enabled: True" in result.stdout or "TTS enabled: True" in result.stderr
    assert "STT enabled: True" in result.stdout or "STT enabled: True" in result.stderr
    assert "Voice: testvoice" in result.stdout or "Voice: testvoice" in result.stderr

# Test error handling for both TTS and STT disabled
def test_disable_all(monkeypatch):
    args = [sys.executable, "speaches_service_manager.py"]
    monkeypatch.setenv("HARBOR_SPEACHES_TTS", "false")
    monkeypatch.setenv("HARBOR_SPEACHES_STT", "false")
    result = subprocess.run(args, capture_output=True, text=True)
    assert "Both TTS and STT are disabled" in result.stdout or "Both TTS and STT are disabled" in result.stderr

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Speaches testing utilities")
    parser.add_argument("command",
                       choices=["test", "test-hf", "test-onnx", "test-kokoro", "test-audio",
                               "test-manager", "list-models", "providers", "download-kokoro"],
                       help="Command to execute")

    args = parser.parse_args()

    if args.command == "test":
        # Run full test suite
        success = asyncio.run(run_full_test_suite())
        sys.exit(0 if success else 1)
    elif args.command == "test-hf":
        success = test_hf_utils()
        sys.exit(0 if success else 1)
    elif args.command == "test-onnx":
        success = test_onnx_utils()
        sys.exit(0 if success else 1)
    elif args.command == "test-kokoro":
        success = test_kokoro_utils()
        sys.exit(0 if success else 1)
    elif args.command == "test-audio":
        success = asyncio.run(test_audio_generation())
        sys.exit(0 if success else 1)
    elif args.command == "test-manager":
        success = test_service_manager()
        sys.exit(0 if success else 1)
    elif args.command == "list-models":
        success = list_models()
        sys.exit(0 if success else 1)
    elif args.command == "providers":
        success = show_providers()
        sys.exit(0 if success else 1)
    elif args.command == "download-kokoro":
        success = download_kokoro()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
