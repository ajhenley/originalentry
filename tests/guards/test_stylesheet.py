"""The stylesheet's own guards.

Tailwind v4 emits **nothing** for an undefined utility: no rule, no build error, no console
warning. If a token is deleted or renamed in `@theme` while markup still says `text-muted`, the
surface simply loses its colour and the page looks finished and is wrong. The same silence covers
a missing font file, which falls back to Georgia without complaint.

The guards: every palette utility the markup uses is emitted by the build; every `@font-face`
file exists; the palette holds its contrast floors; a field borders with muted, not the divider
colour; no retired colour name survives in markup or in `@theme`; and no token is declared
twice. Two meta-tests pin the first guard's own logic (variant and boundary handling, and
longest-token-first matching). They do not judge whether the design is good.

Blind spots. `_utilities_used` only extracts names that exist in `@theme`, so a typo such as
`bg-papr` is invisible to it. It also cannot see class names assembled in Jinja or Python
(`bg-{{ x }}`), `.py` files (not scanned), or anything outside the `templates/` and `static/js/`
roots. The retired-name scan reads only those same roots. It matches a retired name followed by
a word boundary, so a hypothetical `text-gray-500` is reported as `text-gray`: the right call,
but the reported name is the stem rather than the class as written.
"""

import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CSS = ROOT / "originalentry" / "static" / "src" / "app.css"
DIST = ROOT / "originalentry" / "static" / "dist" / "app.css"

#: Tailwind utility prefixes that can take a colour. The compound forms matter: a side-specific
#: utility like `border-t-amber` puts `t-` between the prefix and the colour name, so a list of
#: bare prefixes misses it — and a missed utility is one Tailwind emits no rule for at all.
PALETTE_PREFIXES = (
    "bg", "text", "border", "ring", "from", "to", "via", "decoration",
    "outline", "divide", "placeholder", "accent", "caret", "fill", "stroke", "shadow",
    "border-t", "border-b", "border-l", "border-r", "border-x", "border-y",
    "divide-x", "divide-y", "ring-offset", "outline-offset",
)

#: The palette this stylesheet is supposed to define. Pinned because the emission guard below
#: builds its scan set *from* the defined tokens: deleting a token silently removes it from
#: scrutiny rather than failing anything. This assertion is what makes a deletion loud.
EXPECTED_TOKENS = (
    "ink", "paper", "white", "muted", "rule",
    "notice", "wash", "failure", "tint", "company", "confirm",
)

#: Longest-first only for legibility. The order does not affect matching — Python's `re`
#: backtracks across the alternation — but listing the compound forms at all is essential:
#: without `border-t` in the list, `border-t-amber` does not match anything, because the `t-`
#: sits between the prefix and the colour name.
_PREFIX_ALT = "|".join(sorted(map(re.escape, PALETTE_PREFIXES), key=lambda p: (-len(p), p)))


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
        % (_PREFIX_ALT, "|".join(sorted(map(re.escape, token_names), key=lambda n: (-len(n), n))))
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


def test_the_palette_is_exactly_the_tokens_we_expect():
    """A deleted or renamed token must fail here, because no other guard can see it.

    `_utilities_used` derives its scan set from whatever `@theme` currently declares, so a token
    that disappears takes its own utilities out of the search with it. Every other guard in this
    file then passes while the markup that named it renders with no colour at all.
    """
    assert set(_defined_tokens()) == set(EXPECTED_TOKENS)


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


#: Every pair the interface actually renders, and the floor it must hold. Every row is 4.5, AA for
#: text. `muted` on `tint` (4.95) is the tightest pair in the palette. `rule` is absent on purpose: at 1.41:1 it
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
    # Confirm sits on white in .callout--confirm; the other three are pinned because a callout
    # inherits whatever ground the page it lands on has, and all four are grounds in this app.
    ("confirm", "white", 4.5),
    ("confirm", "paper", 4.5),
    ("confirm", "tint", 4.5),
    ("confirm", "wash", 4.5),
    ("company", "paper", 4.5),
    ("muted", "tint", 4.5),
    ("ink", "tint", 4.5),
    ("notice", "tint", 4.5),
    ("failure", "tint", 4.5),
    ("company", "white", 4.5),
    ("ink", "wash", 4.5),
    ("failure", "wash", 4.5),
    ("muted", "wash", 4.5),
    # Pins the monogram glyphs. It can only test the #1b3a5c fallback: the real accent arrives
    # per-pack at request time.
    ("paper", "company", 4.5),
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


#: Retired with the CityReady palette. Nothing stops a later edit writing `text-navy`; Tailwind
#: would emit no rule for it and the text would lose its colour with no error anywhere. Navy
#: itself survives, but only as --color-company.
RETIRED = (
    "navy-deep", "navy-mid", "navy", "teal-bright", "teal-deep", "teal",
    "amber-deep", "amber", "coral", "cream", "cloud", "silver", "gray", "attention",
)


def test_no_retired_colour_name_survives():
    """Longest-first, so `navy-deep` is never reported as a bare `navy`."""
    pattern = re.compile(r"\b(?:%s)-(?:%s)\b" % (_PREFIX_ALT, "|".join(RETIRED)))
    offences = []
    for path in _scanned_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for hit in pattern.findall(line):
                offences.append(f"{path.relative_to(ROOT)}:{n} {hit}")

    assert not offences, "retired colour names in markup: " + "; ".join(offences)


def test_no_retired_token_is_still_defined():
    defined = set(_defined_tokens())
    lingering = sorted(defined & set(RETIRED))

    assert not lingering, "retired tokens still in @theme: " + ", ".join(lingering)


def test_no_token_is_declared_twice():
    """A duplicate declaration wins silently and makes the first one a lie.

    `_defined_tokens` is a dict, so a second `--color-paper` is invisible to every other guard
    in this file: the tests all pass while half the stylesheet means something else.
    """
    counts = collections.Counter(re.findall(r"--color-([a-z0-9-]+)\s*:", _css_text()))
    duplicates = {name: n for name, n in counts.items() if n > 1}

    assert not duplicates, f"declared more than once: {duplicates}"


def test_a_field_does_not_share_the_page_background():
    """A control whose background matches the page has no surface of its own.

    `--color-paper` meant #ffffff before this palette and #faf8f4 after, so every rule written as
    `background: var(--color-paper)` silently changed from "white" to "the same as the page". The
    design material sets inputs to white explicitly. Nothing else in this file would notice.
    """
    css = _css_text()
    field_block = css[css.index(".field {") : css.index(".field:focus")]
    page_block = css[css.index("  html {") : css.index("  h1,")]

    field_bg = re.search(r"background:\s*var\(--color-([a-z0-9-]+)\)", field_block)
    page_bg = re.search(r"background:\s*var\(--color-([a-z0-9-]+)\)", page_block)

    assert field_bg, f"`.field` declares no background: {field_block}"
    assert page_bg, f"`html` declares no background: {page_block}"
    assert field_bg.group(1) != page_bg.group(1), (
        f"`.field` and the page share a background ({field_bg.group(1)}), "
        "so the control has no visible surface"
    )
