import logging
import middleware.request_id

# Common ANSI color codes for reuse
COLORS = {
  'black': '\033[30m',
  'red': '\033[31m',
  'green': '\033[32m',
  'yellow': '\033[33m',
  'blue': '\033[34m',
  'magenta': '\033[35m',
  'cyan': '\033[36m',
  'white': '\033[37m',
  'gray': '\033[90m',
  'reset': '\033[0m',
  'bold': '\033[1m',
  'underline': '\033[4m'
}

class BoostFormatter(logging.Formatter):
  COLORS = {
    'DEBUG': COLORS['gray'],
    'INFO': COLORS['blue'],
    'WARNING': COLORS['yellow'],
    'ERROR': COLORS['red'],
    'CRITICAL': '\033[41m'  # Keep red background as it's not in COLORS map
  }

  LEVEL_LABELS = {
    'DEBUG': '⏺ ',
    'INFO': '⏺ ',
    'WARNING': '⏺ // ',
    'ERROR': '⏺ !! ',
    'CRITICAL': '⏺ !! '
  }

  def format(self, record):
    color = self.COLORS.get(record.levelname, COLORS['reset'])
    label = self.LEVEL_LABELS.get(record.levelname, record.levelname)
    reset = COLORS['reset']
    # For debug messages, make the entire message gray
    if record.levelname == 'DEBUG':
        record.msg = f"{color}{record.msg}{reset}"
    record.levelname = f"{color}{label}{reset}"

    # Add request ID to log messages
    request_id = middleware.request_id.request_id_var.get()
    if request_id:
      record.levelname = f"{color}{request_id}{reset} {record.levelname}"

    return super().format(record)

formatter = BoostFormatter(
  "%(levelname)s%(name)s %(message)s",
  datefmt="%H:%M:%S"
)

def setup_logger(name):
  logger = logging.getLogger(name)
  if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.set_name(name)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
  return logger
