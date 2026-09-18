#!/usr/bin/env python3
"""Generate a pack zip from an authoring source (T5).

    python scripts/generate_pack.py SOURCE OUT.zip [--paper]

SOURCE is a ``.py`` file exposing a ``SOURCE`` dict, or a ``.json`` file holding it. With images
(the default) the generator renders a PNG per document per variant (needs Pillow); ``--paper``
skips images and produces a paper pack.

Every answer figure is computed by replaying the authored entries through the app's own ledger
engine, and the finished pack is checked against the same rules the upload screen runs — so a pack
this prints is one the catalogue will accept.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parchment.generator import GeneratorError, build, write_zip  # noqa: E402


def _load_source(path: Path) -> dict:
    if path.suffix == ".json":
        return json.loads(path.read_text())
    if path.suffix == ".py":
        spec = importlib.util.spec_from_file_location("_pack_source", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = getattr(module, "SOURCE", None)
        if source is None:
            raise SystemExit(f"{path} has no SOURCE dict.")
        return source
    raise SystemExit(f"Unsupported source type: {path.suffix} (use .py or .json).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a Parchment pack zip.")
    parser.add_argument("source", type=Path, help="authoring source (.py with SOURCE, or .json)")
    parser.add_argument("out", type=Path, help="output .zip path")
    parser.add_argument("--paper", action="store_true", help="skip images (paper pack)")
    args = parser.parse_args(argv)

    source = _load_source(args.source)
    try:
        generated = build(source, render_images=not args.paper)
    except GeneratorError as error:
        print("This pack was not generated. Fix these and try again:", file=sys.stderr)
        for problem in error.problems:
            print(f"  [{problem.rule}] {problem.path}: {problem.message}", file=sys.stderr)
        return 1

    data, digest = write_zip(generated, args.out)
    company = generated.pack.get("company", {})
    print(f"Wrote {args.out} ({len(data) // 1024} KB, sha256 {digest[:12]}…)")
    print(f"  {company.get('name')} v{generated.pack.get('version')} · "
          f"{len(generated.keys)} variant(s) · {len(generated.images)} image(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
