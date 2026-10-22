"""Validate render.yaml against Render's JSON schema (network required once)."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML missing: pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)

SCHEMA_URL = "https://render.com/schema/render.yaml.json"
ROOT = Path(__file__).resolve().parents[1]
RENDER_YAML = ROOT / "render.yaml"


def main() -> int:
    if not RENDER_YAML.is_file():
        print(f"Missing {RENDER_YAML}", file=sys.stderr)
        return 1
    with urllib.request.urlopen(SCHEMA_URL, timeout=60) as resp:
        schema = json.load(resp)
    doc = yaml.safe_load(RENDER_YAML.read_text(encoding="utf-8"))
    try:
        import jsonschema

        jsonschema.validate(doc, schema)
    except ImportError:
        print("jsonschema missing: pip install jsonschema", file=sys.stderr)
        return 2
    except jsonschema.ValidationError as exc:
        print(f"INVALID: {exc.message}", file=sys.stderr)
        return 1
    print("OK render.yaml validates against Render schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
