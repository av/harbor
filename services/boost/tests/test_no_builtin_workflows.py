"""No built-in workflow presets ship by default."""

from pathlib import Path

import yaml


def test_shipped_workflow_file_has_no_builtin_presets():
  workflow_file = Path(__file__).resolve().parent.parent / "src" / "workflows.yaml"
  assert yaml.safe_load(workflow_file.read_text(encoding="utf-8")) == {"workflows": {}}
