"""The stylesheet's own guards.

Tailwind v4 emits **nothing** for an undefined utility: no rule, no build error, no console
warning. If a token is deleted or renamed in `@theme` while markup still says `text-muted`, the
surface simply loses its colour and the page looks finished and is wrong. The same silence covers
a missing font file, which falls back to Georgia without complaint.

There are two guards (every palette utility the markup uses is emitted by the build; every
`@font-face` file exists) plus one meta-test pinning the first guard's own logic. They do not
judge whether the design is good.

Blind spots. `_utilities_used` only extracts names that exist in `@theme`, so a typo such as
`bg-papr` is invisible to it. It also cannot see class names assembled in Jinja or Python
(`bg-{{ x }}`), `.py` files (not scanned), or anything outside the `templates/` and `static/js/`
roots.
"""

import pathlib
import re
import sys

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
        r"\b(?:%s)-(?:%s)(?![\w-])"
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

    Limitation: this verifies the utility is emitted *in some form*. `_utilities_used` discards
    any variant or opacity, so `.hover\\:text-muted` or `.bg-rule\\/50` satisfies a bare
    `text-muted` or `bg-rule`. The specific variant or opacity is not checked; the guard's job is
    to catch a token deleted while markup still names it.
    """
    return re.search(r"(?:\.|\\:)" + re.escape(utility) + r"(?![\w-])", built) is not None


def test_every_palette_class_used_reaches_the_built_css():
    """A token deleted from `@theme` while a template still names it loses the surface.

    The built stylesheet is the evidence: if `text-muted` is used and `.text-muted` is absent
    from `dist/app.css`, every element using it renders with no colour.
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



def test_utilities_used_prefers_the_longest_token_name(tmp_path, monkeypatch):
    """`text-amber-deep` must not also yield a phantom `text-amber`."""
    page = tmp_path / "page.html"
    page.write_text('<p class="text-amber-deep">x</p>', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "_scanned_files", lambda: [page])

    used = _utilities_used({"amber", "amber-deep"})

    assert used == {"text-amber-deep"}, used
    assert "text-amber" not in used


def _relative_luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


#: Every pair the interface actually renders, and the floor it must hold. 4.5 is AA for text;
#: 3.0 is AA for a control's boundary (WCAG 1.4.11). `rule` is absent on purpose: at 1.41:1 it
#: is a decorative divider, which 1.4.11 exempts, and a control that used it would be invisible.
CONTRAST_FLOORS = [
    ("ink", "paper", 4.5),
    ("ink", "white", 4.5),
    ("muted", "paper", 4.5),
    ("muted", "white", 4.5),
    ("notice", "wash", 4.5),
    ("notice", "paper", 4.5),
    ("failure", "white", 4.5),
    ("failure", "paper", 4.5),
    ("company", "paper", 4.5),
    ("paper", "ink", 4.5),
    ("white", "ink", 4.5),
]


def test_the_palette_holds_its_contrast_floors():
    """Lightening a token until text stops being readable must fail here, not in review."""
    tokens = _defined_tokens()
    failures = []
    for fg, bg, floor in CONTRAST_FLOORS:
        assert fg in tokens, f"--color-{fg} is not defined"
        assert bg in tokens, f"--color-{bg} is not defined"
        ratio = _contrast(_token_hex(fg), _token_hex(bg))
        if ratio < floor:
            failures.append(f"{fg} on {bg} is {ratio:.2f}:1, below {floor}:1")

    assert not failures, "; ".join(failures)


def test_a_field_borders_with_muted_not_the_divider_colour():
    """`rule` is 1.41:1 on paper: a field bordered with it has no visible edge.

    Asserted positively as well as negatively. "Does not mention rule" passes on a `.field` that
    mentions no colour at all — including one where the border was deleted outright — so the
    absence alone proves nothing.
    """
    css = _css_text()
    field_block = css[css.index(".field {") : css.index(".field:focus")]

    assert "--color-muted" in field_block, (
        ".field must border with --color-muted (5.80:1); found: " + field_block
    )
    assert "--color-rule" not in field_block, (
        ".field must not border with --color-rule (1.41:1), which leaves no visible edge"
    )
