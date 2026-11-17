"""Export or check the committed OpenAPI document (PROTOCOL §16)."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.main import create_app


def render() -> str:
    app = create_app()
    schema = app.openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export or check docs/openapi.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    path = Path(settings.docs_openapi_path)
    rendered = render()
    if args.check:
        if not path.exists():
            print(f"{path} does not exist; run `make openapi`", file=sys.stderr)
            raise SystemExit(1)
        current = path.read_text(encoding="utf-8")
        if current != rendered:
            diff = "".join(
                difflib.unified_diff(
                    current.splitlines(keepends=True),
                    rendered.splitlines(keepends=True),
                    fromfile=str(path),
                    tofile="generated",
                )
            )
            print(diff, file=sys.stderr)
            raise SystemExit(1)
        print(f"{path} is current")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
