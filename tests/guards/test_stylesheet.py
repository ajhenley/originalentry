"""The stylesheet's own guards.

Tailwind v4 emits **nothing** for an undefined utility. `bg-papr` produces no rule, no build
error and no console warning: the surface simply loses its colour, and a person reading the page
sees a layout that looks finished and is wrong. The same silence covers a missing font file,
which falls back to Georgia without complaint.

These guards exist because a restyle is otherwise unverifiable by test. They do not judge whether
the design is good; they catch the three ways it can be silently broken.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
CSS = ROOT / "originalentry" / "static" / "src" / "app.css"
DIST = ROOT / "originalentry" / "static" / "dist" / "app.css"

#: Tailwind utility prefixes that can take a colour.
PALETTE_PREFIXES = (
    "bg", "text", "border", "ring", "from", "to", "via", "decoration",
    "outline", "divide", "placeholder", "accent", "caret", "fill", "stroke", "shadow",
)


def _css_text() -> str:
    return CSS.read_text(encoding="utf-8")


_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _defined_tokens() -> dict[str, str]:
    """Every ``--color-NAME`` the stylesheet defines, mapped to its literal value."""
    found = {}
    for name, value in re.findall(r"--color-([a-z0-9-]+):\s*([^;]+);", _css_text()):
        found[name] = value.strip().lower()
    return found


def _token_hex(name: str) -> str:
    """The colour a token resolves to.

    ``company`` lives in the ``@theme inline`` block as ``var(--company-accent, #1b3a5c)``,
    because the real accent arrives from the pack at request time. Its fallback is the hex to
    measure, so take the first one in the value rather than assuming the whole value is a colour.
    """
    value = _defined_tokens()[name]
    found = _HEX.search(value)
    assert found, f"--color-{name} resolves to no literal hex: {value}"
    return found.group(0)


def _scanned_files() -> list[pathlib.Path]:
    roots = [
        ROOT / "originalentry" / "templates",
        ROOT / "originalentry" / "static" / "js",
    ]
    files: list[pathlib.Path] = []
    for root in roots:
        files.extend(p for p in root.rglob("*") if p.suffix in {".html", ".js"})
    assert files, "found no templates or scripts to scan — the paths are wrong"
    return files


def _utilities_used(token_names: set[str]) -> set[str]:
    """Palette utilities the markup asks for, e.g. ``{"text-muted", "bg-ink"}``.

    Built from the *defined* token names rather than by guessing which suffixes are colours:
    Tailwind's own vocabulary overlaps these prefixes heavily (`text-sm`, `border-b`,
    `shadow-lg`), so a scan that flagged every unrecognised suffix would be a maintenance
    burden full of false positives. This finds references to names we actually own.
    """
    pattern = re.compile(
        r"\b(?:%s)-(?:%s)\b"
        % ("|".join(PALETTE_PREFIXES), "|".join(sorted(map(re.escape, token_names), key=lambda n: (-len(n), n))))
    )
    used: set[str] = set()
    for path in _scanned_files():
        used.update(pattern.findall(path.read_text(encoding="utf-8")))
    return used


def _emitted(utility: str, built: str) -> bool:
    """Is this utility in the built stylesheet, under any variant?

    Tailwind escapes a variant's colon, so `hover:border-navy` is emitted as
    `.hover\\:border-navy`. A plain `.border-navy` substring test therefore misses every
    variant-prefixed utility, and the markup uses three of them. Accepting either a leading `.`
    or a variant's `\\:` matches both forms, and the trailing lookahead stops `border-navy`
    matching inside `.border-navy-deep`.
    """
    return re.search(r"(?:\.|\\:)" + re.escape(utility) + r"(?![\w-])", built) is not None


def test_every_palette_class_used_reaches_the_built_css():
    """A token deleted from `@theme` while a template still names it loses the surface.

    The built stylesheet is the evidence: if `text-muted` is used and `.text-muted` is absent
    from `dist/app.css`, 162 elements render with no colour.
    """
    tokens = set(_defined_tokens())
    used = _utilities_used(tokens)
    assert used, "scan found no palette utilities at all — the pattern is broken"

    built = DIST.read_text(encoding="utf-8")
    missing = sorted(u for u in used if not _emitted(u, built))

    assert not missing, (
        "used in markup but not emitted by the build — rebuild, or the token is undefined: "
        + ", ".join(missing)
    )


def test_every_font_face_file_exists():
    """A renamed woff2 falls back to Georgia with no error anywhere."""
    srcs = re.findall(r'src:\s*url\("([^"]+)"\)', _css_text())
    assert srcs, "found no @font-face src rules"

    missing = [s for s in srcs if not (CSS.parent / s).resolve().is_file()]

    assert not missing, "@font-face points at files that do not exist: " + ", ".join(missing)


def test_the_emission_check_understands_variants_and_boundaries():
    """The guard's own logic, pinned. Both of these were wrong once.

    A substring test missed variant-prefixed utilities, and an alphabetically ordered
    alternation matched a short token name inside a longer one.
    """
    assert _emitted("border-navy", r".hover\:border-navy{border-color:red}")
    assert _emitted("text-muted", ".text-muted{color:red}")
    assert not _emitted("border-navy", ".border-navy-deep{border-color:red}")
    assert not _emitted("bg-papr", ".bg-paper{background:red}")

    names = sorted(map(re.escape, {"amber", "amber-deep"}), key=lambda n: (-len(n), n))
    assert names[0] == re.escape("amber-deep"), "longer token names must be tried first"
