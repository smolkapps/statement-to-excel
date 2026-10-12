"""The synthetic fixtures must be byte-reproducible.

``make_fixtures.py`` is documented in the README as a step contributors can
re-run to (re)generate the committed PDFs. If the generator is not
deterministic, every regeneration embeds a fresh ``CreationDate``/``ModDate``
(and document ID) and dirties the working tree — so the committed fixtures can
never round-trip. reportlab makes this deterministic via ``invariant=1`` on the
canvas; this test guards that the whole generator stays byte-stable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from tests import make_fixtures

FIX = Path(make_fixtures.__file__).resolve().parent / "fixtures"

GENERATORS_AND_OUTPUTS = [
    (make_fixtures.make_acmebank, "acmebank.pdf"),
    (make_fixtures.make_columnarcredit, "columnarcredit.pdf"),
    (make_fixtures.make_minimalchecking, "minimalchecking.pdf"),
    (make_fixtures.make_scanned_empty, "scanned_empty.pdf"),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_regeneration_is_byte_identical():
    """Generating each fixture twice yields identical bytes (no timestamps)."""
    for generate, name in GENERATORS_AND_OUTPUTS:
        generate()
        first = _sha256(FIX / name)
        generate()
        second = _sha256(FIX / name)
        assert first == second, (
            f"{name} is not reproducible: two regenerations differ, so a "
            f"non-invariant timestamp/ID leaked into the PDF"
        )


def test_committed_fixtures_match_a_fresh_regeneration():
    """The committed PDFs equal what the generator produces right now, so the
    README's regen step leaves the tree clean."""
    committed = {name: _sha256(FIX / name) for _, name in GENERATORS_AND_OUTPUTS}
    for generate, name in GENERATORS_AND_OUTPUTS:
        generate()
    for _, name in GENERATORS_AND_OUTPUTS:
        assert _sha256(FIX / name) == committed[name], (
            f"{name} on disk differs from a fresh regeneration — regenerate and "
            f"commit it"
        )
