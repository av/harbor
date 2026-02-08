import logging

def setup_logger(name):
  logger = logging.getLogger(name)
  if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.set_name(name)
    formatter = logging.Formatter(
      "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
  return logger