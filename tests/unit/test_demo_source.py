"""The demo company that `flask seed demo` builds.

The dev database gets wiped. When it does, the way back has to be one command, and the pack it
builds has to be one the app would have accepted on upload — otherwise the thing you click
through is not the thing students would meet.

This runs the committed authoring source through the real generator and the real validator, so a
source edited into something the upload screen would refuse fails here instead of at 2am.
"""

import json
from pathlib import Path

from originalentry.generator import build
from originalentry.packs import schema
from originalentry.packs.validate import validate_pack

SOURCE = Path(__file__).resolve().parents[2] / "packs" / "riverbend-demo" / "source.json"


def test_the_demo_source_is_where_the_seed_command_looks():
    assert SOURCE.exists(), f"`flask seed demo` reads {SOURCE}"


def test_it_builds_a_pack_the_app_would_accept():
    generated = build(json.loads(SOURCE.read_text()))

    pack = schema.load_pack(generated.pack)
    keys = {code: schema.load_answer_key(key) for code, key in generated.keys.items()}

    assert list(keys) == ["A"]
    assert not list(validate_pack(pack, keys))


def test_it_keeps_its_own_company_slug():
    """Sharing a slug with a test pack is how the seed and the suite wipe each other out."""
    slug = json.loads(SOURCE.read_text())["company"]["slug"]

    assert slug == "riverbend-demo"
    assert slug != "testco-alpha"
