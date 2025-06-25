#!/usr/bin/env python3
"""
Speaches Service Manager for Harbor

This script manages the lifecycle of utility services and processes that support
the main Speaches service in Harbor. It ensures that GPU detection, ONNX provider
setup, and other supporting functionality is properly initialized and managed.

Key Functions:
- Initialize ONNX Runtime providers for optimal performance
- Setup cache directories and environment variables
- Validate Speaches installation and dependencies
- Provide health checks for the service
- Clean shutdown of supporting processes

Usage:
    python speaches_service_manager.py --init         # Initialize service environment
    python speaches_service_manager.py --health       # Check service health
    python speaches_service_manager.py --cleanup      # Clean shutdown
    python speaches_service_manager.py --validate     # Validate installation
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict

# Add current directory to path to import local modules
sys.path.insert(0, str(Path(__file__).parent))

try:
    from onnx_utils import ONNXProviderDetector
    from kokoro_utils import setup_kokoro_providers, create_gpu_kokoro, test_kokoro_gpu_acceleration
    from hf_utils import get_kokoro_model_path, download_kokoro_model, list_local_model_ids, does_local_model_exist
except ImportError:
    ONNXProviderDetector = None
    setup_kokoro_providers = None
    create_gpu_kokoro = None
    test_kokoro_gpu_acceleration = None
    get_kokoro_model_path = None
    download_kokoro_model = None
    list_local_model_ids = None
    does_local_model_exist = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SpeachesServiceManager:
    """Manages the lifecycle and supporting services for Speaches in Harbor."""

    def __init__(self):
        self.harbor_home = os.environ.get('HARBOR_HOME', os.getcwd())
        self.service_dir = Path(__file__).parent
        self.cache_dir = Path(os.environ.get('HARBOR_HF_CACHE',
                                           os.path.expanduser('~/.cache/huggingface/hub')))
        self.log_dir = Path(self.harbor_home) / 'app' / 'backend' / 'data' / 'logs'
        self.pid_dir = Path(self.harbor_home) / 'app' / 'backend' / 'data' / 'pids'

        # Ensure required directories exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.pid_dir.mkdir(parents=True, exist_ok=True)

    def initialize_environment(self) -> bool:
        """Initialize the service environment for optimal performance."""
        logger.info("Initializing Speaches service environment...")

        try:
            # 1. Setup ONNX Runtime providers
            if not self._setup_onnx_providers():
                logger.warning("ONNX provider setup failed, continuing with defaults")

            # 2. Setup cache directories
            self._setup_cache_directories()

            # 3. Setup environment variables
            self._setup_environment_variables()

            # 4. Ensure required models are available
            if not self._ensure_models_available():
                logger.warning("Model setup failed, some functionality may be limited")

            # 5. Validate dependencies
            if not self._validate_dependencies():
                logger.error("Dependency validation failed")
                return False

            logger.info("Service environment initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize service environment: {e}")
            return False

    def _setup_onnx_providers(self) -> bool:
        """Setup ONNX Runtime providers for optimal performance."""
        if ONNXProviderDetector is None:
            logger.warning("ONNX provider detector not available")
            return False

        try:
            detector = ONNXProviderDetector()
            env_vars = detector.setup_environment()

            # Write provider info to log
            info = detector.get_provider_info()
            logger.info(f"ONNX providers configured: {info['detected_providers']}")

            # Export environment variables for the main process
            for key, value in env_vars.items():
                os.environ[key] = value

            return True

        except Exception as e:
            logger.error(f"Failed to setup ONNX providers: {e}")
            return False

    def _setup_cache_directories(self):
        """Setup and validate cache directories."""
        cache_dirs = [
            self.cache_dir,
            self.cache_dir / 'models',
            self.cache_dir / 'speaches',
        ]

        for cache_dir in cache_dirs:
            cache_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Cache directory ready: {cache_dir}")

    def load_default_config(self) -> dict:
        """Load default configuration from YAML file."""
        config_file = self.service_dir / 'config_defaults.yml'

        if not config_file.exists():
            logger.warning(f"Default config file not found: {config_file}")
            return {}

        try:
            import yaml

            with open(config_file) as f:
                config_text = f.read()

            # Substitute environment variables
            config_text = self._substitute_env_vars(config_text)

            config = yaml.safe_load(config_text)
            logger.info(f"Loaded default configuration from {config_file}")
            return config

        except ImportError:
            logger.warning("PyYAML not available, using minimal default config")
            return self._get_minimal_config()
        except Exception as e:
            logger.error(f"Failed to load default config: {e}")
            return self._get_minimal_config()

    def _substitute_env_vars(self, text: str) -> str:
        """Substitute environment variables in config text."""
        import os
        import re

        def replace_var(match):
            var_name = match.group(1)
            default_value = match.group(3) if match.group(3) else ""
            return os.environ.get(var_name, default_value)

        # Replace ${VAR} and ${VAR:-default} patterns
        pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'
        return re.sub(pattern, replace_var, text)

    def _get_minimal_config(self) -> dict:
        """Get minimal configuration when YAML loading fails."""
        return {
            'server': {
                'host': '0.0.0.0',
                'port': 34331,
                'log_level': 'info',
                'workers': 1,
                'max_concurrent_requests': 10,
                'timeout': 30,
            },
            'models': {
                'tts': {
                    'default_model': 'hexgrad/Kokoro-82M',
                    'default_voice': 'af_bella'
                },
                'stt': {
                    'default_model': 'Systran/faster-distil-whisper-large-v3'
                }
            },
            'performance': {
                'onnx': {
                    'providers': 'auto'
                }
            }
        }

    def _setup_environment_variables(self):
        """Setup required environment variables using configuration hierarchy."""
        # Load configuration to get model settings
        config = self.load_default_config()

        env_vars = {
            'HF_HUB_CACHE': str(self.cache_dir),
            'TRANSFORMERS_CACHE': str(self.cache_dir / 'transformers'),
            'SPEACHES_CACHE_DIR': str(self.cache_dir / 'speaches'),
        }

        # Add model-specific environment variables using configuration hierarchy
        # Priority: existing env vars > config file values
        tts_model = config.get('models', {}).get('tts', {}).get('default_model')
        if tts_model and 'SPEACHES_TTS_MODEL' not in os.environ:
            env_vars['SPEACHES_TTS_MODEL'] = tts_model

        tts_voice = config.get('models', {}).get('tts', {}).get('default_voice')
        if tts_voice and 'SPEACHES_TTS_VOICE' not in os.environ:
            env_vars['SPEACHES_TTS_VOICE'] = tts_voice

        stt_model = config.get('models', {}).get('stt', {}).get('default_model')
        if stt_model and 'SPEACHES_STT_MODEL' not in os.environ:
            env_vars['SPEACHES_STT_MODEL'] = stt_model

        # Set environment variables that aren't already present
        for key, value in env_vars.items():
            if key not in os.environ:
                os.environ[key] = value
                logger.debug(f"Set environment variable: {key}={value}")
            else:
                logger.debug(f"Using existing environment variable: {key}={os.environ[key]}")

    def _ensure_models_available(self) -> bool:
        """Ensure required models are downloaded and available."""
        if get_kokoro_model_path is None or download_kokoro_model is None:
            logger.warning("HuggingFace utilities not available for model management")
            return False

        try:
            logger.info("Ensuring Kokoro TTS model is available...")

            # Download Kokoro model if needed
            download_kokoro_model()

            # Verify model path exists
            model_path = get_kokoro_model_path()
            if not model_path.exists():
                logger.error(f"Kokoro model not found at expected path: {model_path}")
                return False

            logger.info(f"Kokoro model available at: {model_path}")

            # Log available local models for debugging
            if list_local_model_ids is not None:
                try:
                    local_models = list_local_model_ids()
                    logger.debug(f"Found {len(local_models)} local HuggingFace models")
                except Exception as e:
                    logger.debug(f"Failed to list local models: {e}")

            return True

        except Exception as e:
            logger.error(f"Failed to ensure models are available: {e}")
            return False

    def _validate_dependencies(self) -> bool:
        """Validate that required dependencies are available."""
        required_modules = ['speaches']
        optional_modules = ['onnxruntime', 'torch', 'transformers']

        missing_required = []
        missing_optional = []

        for module in required_modules:
            try:
                __import__(module)
                logger.debug(f"Required module available: {module}")
            except ImportError:
                missing_required.append(module)
                logger.error(f"Required module missing: {module}")

        for module in optional_modules:
            try:
                __import__(module)
                logger.debug(f"Optional module available: {module}")
            except ImportError:
                missing_optional.append(module)
                logger.debug(f"Optional module missing: {module}")

        if missing_required:
            logger.error(f"Missing required modules: {missing_required}")
            return False

        if missing_optional:
            logger.info(f"Missing optional modules (may affect performance): {missing_optional}")

        return True

    def health_check(self) -> dict[str, any]:
        """Perform a comprehensive health check of the service."""
        health = {
            'status': 'healthy',
            'timestamp': time.time(),
            'checks': {}
        }

        try:
            # Check dependencies
            health['checks']['dependencies'] = self._validate_dependencies()

            # Check cache directories
            health['checks']['cache_directories'] = all(
                cache_dir.exists() for cache_dir in [
                    self.cache_dir,
                    self.cache_dir / 'models',
                    self.cache_dir / 'speaches'
                ]
            )

            # Check ONNX providers
            if ONNXProviderDetector:
                detector = ONNXProviderDetector()
                health['checks']['onnx_providers'] = detector.test_providers()
                health['onnx_info'] = detector.get_provider_info()
            else:
                health['checks']['onnx_providers'] = False
                health['onnx_info'] = {'error': 'ONNX detector not available'}

            # Check model availability
            health['checks']['models_available'] = self._check_model_availability()

            # Check Kokoro TTS functionality
            health['checks']['kokoro_gpu'] = self.test_kokoro_functionality()

            # Check Speaches availability
            try:
                import speaches
                health['checks']['speaches_module'] = True
                health['speaches_version'] = getattr(speaches, '__version__', 'unknown')
            except ImportError:
                health['checks']['speaches_module'] = False

            # Overall status
            if not all(health['checks'].values()):
                health['status'] = 'degraded'

        except Exception as e:
            health['status'] = 'unhealthy'
            health['error'] = str(e)
            logger.error(f"Health check failed: {e}")

        return health

    def cleanup(self):
        """Clean shutdown of supporting processes and services."""
        logger.info("Cleaning up Speaches service...")

        try:
            # Clean up any temporary files
            temp_files = [
                self.service_dir / '.speaches_temp',
                self.cache_dir / 'speaches' / '.temp'
            ]

            for temp_file in temp_files:
                if temp_file.exists():
                    if temp_file.is_file():
                        temp_file.unlink()
                    elif temp_file.is_dir():
                        import shutil
                        shutil.rmtree(temp_file)
                    logger.debug(f"Cleaned up temporary file: {temp_file}")

            logger.info("Service cleanup completed")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def validate_installation(self) -> bool:
        """Validate the Speaches installation and configuration."""
        logger.info("Validating Speaches installation...")

        try:
            # Check if Speaches can be imported
            import speaches
            logger.info(f"Speaches module found (version: {getattr(speaches, '__version__', 'unknown')})")

            # Check if we can create the app (skip if not available)
            try:
                from speaches.main import create_app
                app = create_app()  # noqa: F841
                logger.info("Speaches app creation successful")
            except ImportError:
                logger.warning("Speaches main module not available, skipping app creation test")
            except Exception as e:
                logger.error(f"Failed to create Speaches app: {e}")
                return False

            # Check ONNX Runtime
            if ONNXProviderDetector:
                detector = ONNXProviderDetector()
                if detector.test_providers():
                    logger.info("ONNX Runtime validation successful")
                else:
                    logger.warning("ONNX Runtime validation failed")

            # Check model availability
            if self._check_model_availability():
                logger.info("Model availability validation successful")
            else:
                logger.warning("Model availability validation failed")

            logger.info("Installation validation completed successfully")
            return True

        except ImportError as e:
            logger.error(f"Speaches module not found: {e}")
            return False
        except Exception as e:
            logger.error(f"Installation validation failed: {e}")
            return False

    def test_kokoro_functionality(self) -> bool:
        """Test Kokoro TTS functionality with GPU acceleration."""
        if test_kokoro_gpu_acceleration is None:
            logger.warning("Kokoro utilities not available for testing")
            return False

        try:
            logger.info("Testing Kokoro TTS GPU acceleration...")
            success = test_kokoro_gpu_acceleration()

            if success:
                logger.info("Kokoro TTS GPU acceleration test passed")
            else:
                logger.warning("Kokoro TTS GPU acceleration test failed, CPU fallback will be used")

            return success

        except Exception as e:
            logger.error(f"Kokoro functionality test failed: {e}")
            return False

    def start_server(self, host: str = None, port: int = None, tts_model: str = None,
                     stt_model: str = None, tts_voice: str = None, **kwargs):
        """
        Start the Speaches server with proper initialization and configuration hierarchy.

        The Speaches server handles both TTS (Text-to-Speech) and STT (Speech-to-Text)
        on a single port/process, allowing simultaneous operations without blocking.

        Configuration Hierarchy (highest to lowest priority):
        1. CLI arguments (passed to this method)
        2. Environment variables (HARBOR_SPEACHES_* and SPEACHES_*)
        3. YAML configuration file (config_defaults.yml)
        4. Built-in defaults

        Args:
            host (str, optional): Host to bind to. Defaults via hierarchy:
                - CLI: --host argument
                - ENV: SPEACHES_HOST
                - YAML: server.host
                - DEFAULT: '0.0.0.0' (bind to all interfaces)

            port (int, optional): Port to bind to. Defaults via hierarchy:
                - CLI: --port argument
                - ENV: HARBOR_SPEACHES_HOST_PORT
                - YAML: server.port
                - DEFAULT: 34331 (matches Harbor container mapping)

            tts_model (str, optional): TTS model ID. Defaults via hierarchy:
                - CLI: --tts-model argument
                - ENV: HARBOR_SPEACHES_TTS_MODEL
                - YAML: models.tts.default_model
                - DEFAULT: 'hexgrad/Kokoro-82M'

            stt_model (str, optional): STT model ID. Defaults via hierarchy:
                - CLI: --stt-model argument
                - ENV: HARBOR_SPEACHES_STT_MODEL
                - YAML: models.stt.default_model
                - DEFAULT: 'Systran/faster-distil-whisper-large-v3'

            tts_voice (str, optional): TTS voice name. Defaults via hierarchy:
                - CLI: --tts-voice argument
                - ENV: HARBOR_SPEACHES_TTS_VOICE
                - YAML: models.tts.default_voice
                - DEFAULT: 'af_bella'

        Examples:
            # Use all defaults
            manager.start_server()

            # Override host and port via CLI
            manager.start_server(host='127.0.0.1', port=8080)

            # Use custom models
            manager.start_server(
                tts_model='custom/tts-model',
                stt_model='custom/stt-model',
                tts_voice='custom_voice'
            )

        Environment Variable Examples:
            export HARBOR_SPEACHES_HOST_PORT=8080
            export HARBOR_SPEACHES_TTS_MODEL=custom/model
            export SPEACHES_HOST=127.0.0.1

        The server starts a single uvicorn process that handles:
        - TTS requests at /api/tts/ endpoints
        - STT requests at /api/stt/ endpoints
        - Voice synthesis and speech recognition can run concurrently
        - Non-blocking async request handling for simultaneous operations
        """

        # Get effective configuration using hierarchy: CLI > Env > YAML > Defaults
        effective_config = self.get_effective_config(
            host=host, port=port, tts_model=tts_model,
            stt_model=stt_model, tts_voice=tts_voice
        )

        final_host = effective_config['server']['host']
        final_port = effective_config['server']['port']

        logger.info(f"Starting Speaches server on {final_host}:{final_port}")
        logger.info(f"TTS Model: {effective_config['models']['tts']['default_model']}")
        logger.info(f"TTS Voice: {effective_config['models']['tts']['default_voice']}")
        logger.info(f"STT Model: {effective_config['models']['stt']['default_model']}")

        try:
            # Set model environment variables from effective config
            os.environ['SPEACHES_TTS_MODEL'] = effective_config['models']['tts']['default_model']
            os.environ['SPEACHES_TTS_VOICE'] = effective_config['models']['tts']['default_voice']
            os.environ['SPEACHES_STT_MODEL'] = effective_config['models']['stt']['default_model']

            # Initialize environment first
            if not self.initialize_environment():
                logger.error("Failed to initialize environment")
                sys.exit(1)

            # Validate installation
            if not self.validate_installation():
                logger.error("Installation validation failed")
                sys.exit(1)

            logger.info("Environment initialization completed, starting Speaches server...")

            # Import and start Speaches
            try:
                import uvicorn
                from speaches.main import create_app

                # Create the app
                app = create_app()

                # Configure uvicorn with effective configuration
                uvicorn_config = uvicorn.Config(
                    app,
                    host=final_host,
                    port=final_port,
                    log_level=effective_config['server']['log_level'],
                    access_log=True,
                    workers=effective_config['server']['workers'],
                    timeout_keep_alive=effective_config['server']['timeout'],
                    **kwargs
                )

                # Start the server
                server = uvicorn.Server(uvicorn_config)
                server.run()

            except ImportError as e:
                logger.error(f"Failed to import required Speaches modules: {e}")
                logger.error("Please ensure Speaches is properly installed")
                sys.exit(1)
            except Exception as e:
                logger.error(f"Failed to start Speaches server: {e}")
                sys.exit(1)

        except KeyboardInterrupt:
            logger.info("Server shutdown requested")
            self.cleanup()
        except Exception as e:
            logger.error(f"Server startup failed: {e}")
            self.cleanup()
            sys.exit(1)

    def _check_model_availability(self) -> bool:
        """Check if required models are available."""
        config = self.load_default_config()
        available_models = 0
        total_expected = 0

        # Check TTS model (Kokoro)
        if get_kokoro_model_path is not None:
            total_expected += 1
            try:
                model_path = get_kokoro_model_path()
                if model_path.exists():
                    logger.debug(f"TTS model (Kokoro) found at: {model_path}")
                    available_models += 1
                else:
                    logger.warning(f"TTS model (Kokoro) not found at: {model_path}")
            except Exception as e:
                logger.error(f"TTS model check failed: {e}")
        else:
            logger.debug("TTS model utilities not available")

        # Check STT model availability (basic check - Speaches will download if needed)
        stt_model = config.get('models', {}).get('stt', {}).get('default_model')
        if stt_model:
            total_expected += 1
            # For STT, we just check if the model name is valid format
            # Speaches will handle downloading Whisper models as needed
            if stt_model and '/' in stt_model:  # HuggingFace format check
                logger.debug(f"STT model configured: {stt_model}")
                available_models += 1
            else:
                logger.warning(f"STT model format invalid: {stt_model}")

        success_rate = available_models / total_expected if total_expected > 0 else 0
        logger.info(f"Model availability: {available_models}/{total_expected} models ready ({success_rate:.1%})")

        # Return true if at least one model is available (partial functionality is acceptable)
        return available_models > 0

    def resolve_config_value(self, config_path: str, env_var: str = None, cli_value=None, default=None):
        """
        Resolve configuration value using hierarchy: CLI args > Env vars > YAML config > Default

        Args:
            config_path: Dot notation path in config (e.g., 'server.host', 'models.tts.default_model')
            env_var: Environment variable name to check
            cli_value: Value provided via command line arguments
            default: Default value if none found

        Returns:
            Resolved configuration value
        """
        # Priority 1: Command line argument (highest priority)
        if cli_value is not None:
            logger.debug(f"Using CLI value for {config_path}: {cli_value}")
            return cli_value

        # Priority 2: Environment variable
        if env_var and env_var in os.environ:
            value = os.environ[env_var]
            # Handle type conversion for port numbers
            if 'PORT' in env_var and value.isdigit():
                value = int(value)
            logger.debug(f"Using environment variable {env_var} for {config_path}: {value}")
            return value

        # Priority 3: YAML configuration file
        config = self.load_default_config()
        keys = config_path.split('.')
        value = config

        try:
            for key in keys:
                value = value[key]
            logger.debug(f"Using config file value for {config_path}: {value}")
            return value
        except (KeyError, TypeError):
            pass

        # Priority 4: Default value (lowest priority)
        if default is not None:
            logger.debug(f"Using default value for {config_path}: {default}")
            return default

        logger.debug(f"No value found for {config_path}")
        return None

    def get_effective_config(self, host=None, port=None, tts_model=None, stt_model=None, tts_voice=None):
        """
        Get effective configuration using the configuration hierarchy.

        Args:
            host: CLI-provided host value
            port: CLI-provided port value
            tts_model: CLI-provided TTS model
            stt_model: CLI-provided STT model
            tts_voice: CLI-provided TTS voice

        Returns:
            Dictionary with resolved configuration values
        """
        return {
            'server': {
                'host': self.resolve_config_value('server.host', 'SPEACHES_HOST', host, '0.0.0.0'),
                'port': self.resolve_config_value('server.port', 'HARBOR_SPEACHES_HOST_PORT', port, int(os.environ.get('HARBOR_SPEACHES_HOST_PORT', '34331'))),
                'log_level': self.resolve_config_value('server.log_level', 'SPEACHES_LOG_LEVEL', None, 'info'),
                'workers': self.resolve_config_value('server.workers', 'SPEACHES_WORKERS', None, 1),
                'max_concurrent_requests': self.resolve_config_value('server.max_concurrent_requests', 'SPEACHES_MAX_REQUESTS', None, 10),
                'timeout': self.resolve_config_value('server.timeout', 'SPEACHES_TIMEOUT', None, 30),
            },
            'models': {
                'tts': {
                    'default_model': self.resolve_config_value('models.tts.default_model', 'HARBOR_SPEACHES_TTS_MODEL', tts_model, 'hexgrad/Kokoro-82M'),
                    'default_voice': self.resolve_config_value('models.tts.default_voice', 'HARBOR_SPEACHES_TTS_VOICE', tts_voice, 'af_bella'),
                },
                'stt': {
                    'default_model': self.resolve_config_value('models.stt.default_model', 'HARBOR_SPEACHES_STT_MODEL', stt_model, 'Systran/faster-distil-whisper-large-v3'),
                }
            },
            'performance': {
                'onnx': {
                    'providers': self.resolve_config_value('performance.onnx.providers', 'HARBOR_ONNX_PROVIDER', None, 'auto'),
                }
            }
        }

    # ...existing code...
def start_server():
    """Entry point for starting the Speaches server."""
    import argparse

    parser = argparse.ArgumentParser(description='Start Speaches Server')
    parser.add_argument('--host', default=None, help='Host to bind to')
    parser.add_argument('--port', type=int, default=None, help='Port to bind to')
    parser.add_argument('--tts-model', default=None, help='TTS model to use (e.g., hexgrad/Kokoro-82M)')
    parser.add_argument('--stt-model', default=None, help='STT model to use (e.g., Systran/faster-distil-whisper-large-v3)')
    parser.add_argument('--tts-voice', default=None, help='TTS voice to use (e.g., af_bella)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    manager = SpeachesServiceManager()
    manager.start_server(
        host=args.host,
        port=args.port,
        tts_model=args.tts_model,
        stt_model=args.stt_model,
        tts_voice=args.tts_voice
    )

def main():
    """CLI interface for the service manager."""
    import argparse

    parser = argparse.ArgumentParser(description='Speaches Service Manager for Harbor')
    parser.add_argument('--init', action='store_true',
                       help='Initialize service environment')
    parser.add_argument('--health', action='store_true',
                       help='Perform health check')
    parser.add_argument('--cleanup', action='store_true',
                       help='Clean shutdown')
    parser.add_argument('--validate', action='store_true',
                       help='Validate installation')
    parser.add_argument('--server', action='store_true',
                       help='Start the Speaches server')
    parser.add_argument('--host', default=None,
                       help='Host to bind to (used with --server)')
    parser.add_argument('--port', type=int, default=None,
                       help='Port to bind to (used with --server)')
    parser.add_argument('--tts-model', default=None,
                       help='TTS model to use (used with --server)')
    parser.add_argument('--stt-model', default=None,
                       help='STT model to use (used with --server)')
    parser.add_argument('--tts-voice', default=None,
                       help='TTS voice to use (used with --server)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    manager = SpeachesServiceManager()

    if args.init:
        success = manager.initialize_environment()
        sys.exit(0 if success else 1)

    elif args.health:
        health = manager.health_check()
        print(json.dumps(health, indent=2))
        sys.exit(0 if health['status'] == 'healthy' else 1)

    elif args.cleanup:
        manager.cleanup()
        sys.exit(0)

    elif args.validate:
        success = manager.validate_installation()
        sys.exit(0 if success else 1)

    elif args.server:
        manager.start_server(
            host=args.host,
            port=args.port,
            tts_model=args.tts_model,
            stt_model=args.stt_model,
            tts_voice=args.tts_voice
        )

    else:
        # Default: initialize and validate
        if not manager.initialize_environment():
            sys.exit(1)
        if not manager.validate_installation():
            sys.exit(1)
        print("Speaches service manager: All checks passed")

if __name__ == '__main__':
    main()
