#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from huggingface_hub.constants import HF_HUB_CACHE

uid, gid = int(os.environ["EXPECT_UID"]), int(os.environ["EXPECT_GID"])
assert (os.getuid(), os.getgid()) == (uid, gid)
assert os.environ["HOME"] == "/tmp"
assert os.environ["HF_HOME"] == "/cache"
assert Path("/etc/passwd").stat().st_uid == 0
cache = Path(HF_HUB_CACHE)
assert cache == Path("/cache/hub")
cache.mkdir(parents=True, exist_ok=True)
probe = cache / "download-probe"
probe.write_text("downloaded")
assert (probe.stat().st_uid, probe.stat().st_gid) == (uid, gid)
if sys.argv[1] != "fresh":
    model = cache / "models--test/blobs"
    (model / "root-owned").write_text("resumed")
    assert (model / "root-owned").stat().st_uid == uid
    assert (model / "keep").stat().st_uid == 23456
    assert Path("/cache/unrelated/keep").stat().st_uid == 0
    for name in ("xet", "assets"):
        (Path("/cache") / name / "probe").write_text("writable")
    for name in ("token", "stored_tokens"):
        (Path("/cache") / name).write_text("")
print(f"PASS: {sys.argv[1]} cache works as host user with the existing HF image")
