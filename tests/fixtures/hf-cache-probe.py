#!/usr/bin/env python3
import os
from pathlib import Path

from huggingface_hub.constants import HF_HUB_CACHE

assert os.getuid() == 12345
assert os.getgid() == 12346
assert "SSL_CERT_FILE" not in os.environ
assert "REQUESTS_CA_BUNDLE" not in os.environ
cache = Path(HF_HUB_CACHE)
cache.mkdir(parents=True, exist_ok=True)
probe = cache / "download-probe"
probe.write_text("downloaded")
assert (probe.stat().st_uid, probe.stat().st_gid) == (12345, 12346)
assert (cache.parent / "existing/keep").stat().st_uid == 23456
print("PASS: cache writable as host user; existing file ownership preserved")
