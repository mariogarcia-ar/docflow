"""Tests for the routing decision (`scripts/poc/decide.py`).

These call :func:`decide.decide` directly — no adapter, no file, no render, no OCR.
That is the whole point of the module: the rule is checkable without paying for the
route it chooses, which was not true while the decision lived inside the driver that
performed it.

The case that motivated the module is
``test_an_illegible_page_goes_aside_before_anything_reads_it``: measured on the
committed scan fixture, a page K3 calls `illegible` cost **9.2 s** of OCR and returned
nothing, because nothing asked the question first.

**These are not the project's four QA gates** — `scripts/poc/` is not in
`testpaths`, and `pytest` does not collect it. They run by path:

    python -m pytest scripts/poc/test_decide.py -q

They are written here, beside the module they cover, because that is where a reader of
`decide.py` looks for its contract, and because the bench's other checks are scripts
rather than suites.
"""

from __future__ import annotations

import decide
import pytest

#: K2's vocabulary, stated once for the tests. `pdf.TEXT_SHAPES` is the real owner;
#: this file duplicates the two names deliberately so the suite does **not** import
#: an adapter, which is the property `decide` exists to preserve. The pairing against
#: the adapter's own constant is asserted in `test_the_text_shapes_are_k2s` below.
TEXT_SHAPES: frozenset[str] = frozenset({"text", "mixed"})


def test_a_text_page_is_read_from_its_text() -> None:
    """`text` needs no pixels: the layer is already there."""
    verdict = decide.decide(shape="text", text_shapes=TEXT_SHAPES)

    assert verdict.route == decide.TEXT
    assert verdict.proceeds is True


def test_a_mixed_page_is_read_from_its_text() -> None:
    """`mixed` carries both, and text is what it is read from.

    Not a free choice: `mixed` is *in* the text shapes because the text layer is
    already there and needs nothing rendered. The pair with the test below is the
    argument — the same measurement vocabulary, two routes.
    """
    verdict = decide.decide(shape="mixed", text_shapes=TEXT_SHAPES)

    assert verdict.route == decide.TEXT


def test_an_image_page_needs_its_pixels() -> None:
    """`image` has no text layer, so the pixels are the only material."""
    verdict = decide.decide(shape="image", text_shapes=TEXT_SHAPES, legibility="ok")

    assert verdict.route == decide.PIXELS
    assert verdict.proceeds is True


def test_an_illegible_page_goes_aside_before_anything_reads_it() -> None:
    """The case the module exists for: refuse *before* paying for the read.

    Measured on `pdf_escaneados/3ac5a2ec-…`: K3 reports `illegible` (sharpness 98.80
    against a threshold of 100), and the OCR that ran anyway took **9.2 s** and
    returned nothing. The decision is now taken from the reading, not after the cost.
    """
    verdict = decide.decide(
        shape="image",
        text_shapes=TEXT_SHAPES,
        legibility="illegible",
        sharpness=98.80,
        threshold=100.0,
    )

    assert verdict.route == decide.ASIDE
    assert verdict.proceeds is False
    # The reason names the numbers, so a reader can check the rule instead of
    # trusting the verdict.
    assert "98.8" in verdict.reason
    assert "100" in verdict.reason


def test_an_illegible_reading_does_not_refuse_a_text_page() -> None:
    """Legibility gates the *pixel* route, and a text page never takes it.

    A page whose text layer reads fine can still have a blurred image inside it. The
    `mixed` fixture is exactly that: 1 060 characters and two images. Refusing it for
    a picture nobody was going to look at would discard a good extraction — so this
    test is the guard against "check legibility early" being read as "check it
    always".
    """
    verdict = decide.decide(
        shape="mixed",
        text_shapes=TEXT_SHAPES,
        legibility="illegible",
        sharpness=12.0,
        threshold=100.0,
    )

    assert verdict.route == decide.TEXT


def test_a_blank_page_goes_aside_with_its_own_reason() -> None:
    """Nothing to read is not the same answer as nothing readable."""
    blank = decide.decide(shape="blank", text_shapes=TEXT_SHAPES)
    illegible = decide.decide(
        shape="image", text_shapes=TEXT_SHAPES, legibility="illegible"
    )

    assert blank.route == illegible.route == decide.ASIDE
    assert blank.reason != illegible.reason


def test_an_unmeasurable_page_goes_aside_rather_than_to_ocr() -> None:
    """*We could not look* must not become *it needs reading*.

    The tempting branch is the conservative-looking one — treat an unmeasured page as
    an image and render it. That is the branch that costs a render **and** an OCR to
    answer a question nobody answered the first time, so it is refused instead, and
    the reason says the shape was never measured rather than that it was blank.
    """
    verdict = decide.decide(shape="", text_shapes=TEXT_SHAPES)

    assert verdict.route == decide.ASIDE
    assert "could not be measured" in verdict.reason


def test_a_legibility_refusal_is_not_reported_as_illegibility() -> None:
    """`unsupported_format` is a fact about the file; `illegible` about its quality.

    Both go aside, and the reasons must differ: a caller reading *blur* when the file
    could not be opened is being told to raise a resolution that was never the
    problem.
    """
    refused = decide.decide(
        shape="image", text_shapes=TEXT_SHAPES, legibility="unsupported_format"
    )
    illegible = decide.decide(
        shape="image", text_shapes=TEXT_SHAPES, legibility="illegible"
    )

    assert refused.route == illegible.route == decide.ASIDE
    assert refused.reason != illegible.reason
    assert "could not be measured" in refused.reason


def test_the_evidence_travels_with_the_decision() -> None:
    """A caller never re-measures to find out why the route was chosen.

    A second measurement is a second answer, and on a sampled kernel it is also a
    second cost — the rule the drivers already follow for their attempts.
    """
    verdict = decide.decide(
        shape="image",
        text_shapes=TEXT_SHAPES,
        legibility="ok",
        sharpness=781.94,
        threshold=100.0,
        measured_dpi=100,
        min_chars=40,
    )

    assert verdict.measured["sharpness"] == 781.94
    assert verdict.measured["measured_dpi"] == 100
    assert verdict.measured["min_chars"] == 40


def test_adapt_is_false_and_stays_declared() -> None:
    """No route adapts, and the field is asserted rather than left unreachable.

    `RasterEngine.rescale` never enlarges (`kernel-cli.md` §14, "Never"), so a page
    that rendered at its own ceiling has nothing to adapt *to*. The field is declared
    anyway so that the day the kernel can enlarge, the answer has somewhere to go —
    and this test fails the moment a route silently starts setting it, which is what
    a caller would need to know about.
    """
    for shape, legibility in (
        ("text", ""),
        ("mixed", "illegible"),
        ("image", "ok"),
        ("blank", ""),
        ("", ""),
    ):
        verdict = decide.decide(
            shape=shape, text_shapes=TEXT_SHAPES, legibility=legibility
        )
        assert verdict.adapt is False, shape


def test_the_text_shapes_this_file_states_are_k2s() -> None:
    """The vocabulary the tests inject is the one K2 actually measures.

    **This is the pairing that keeps the injection honest.** `decide` takes
    `text_shapes` rather than owning it, so that `pdf.TEXT_SHAPES` stays the single
    owner — but a caller could then inject anything, and these tests would pass while
    the real driver routed on a different mapping. Comparing the two sets is what
    makes *one owner* a checked fact instead of a stated intention.

    The import is **function-local**: it reaches an adapter, and this module is
    adapter-free at import time on purpose, so the dependency is confined to the one
    test that must have it.
    """
    # pylint: disable=import-outside-toplevel
    import pdf as pdf_driver

    assert set(TEXT_SHAPES) == set(pdf_driver.TEXT_SHAPES)


@pytest.mark.parametrize(
    "shape", ["text", "mixed", "image", "blank", "", "something-new"]
)
def test_every_shape_produces_a_route_and_a_reason(shape: str) -> None:
    """No input falls through, and none returns a route without saying why.

    `something-new` is the one that matters: a shape this module has never seen must
    still be routed rather than raising, because K2's vocabulary is not frozen here
    and a crash on a new word would be a defect in the caller's run.
    """
    verdict = decide.decide(shape=shape, text_shapes=TEXT_SHAPES)

    assert verdict.route in {decide.TEXT, decide.PIXELS, decide.ASIDE}
    assert verdict.reason
