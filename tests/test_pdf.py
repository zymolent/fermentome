"""Tests for `fermdb.extract.pdf`.

The reason `harness._decode_text` refused PDFs outright was sound — *"a PDF read as text produces
plausible garbage, and a model will happily quote from it"* — and adding an extractor does not
retire that reasoning, it relocates it. A scanned PDF still produces garbage, and pypdf returns it
without complaining. So most of what follows is about the refusals.

The PDFs are built here rather than committed as fixtures: a few hundred bytes of hand-written
PDF is easier to reason about than an opaque binary, and it lets a test construct exactly the
pathological case it needs.
"""

from __future__ import annotations

import pytest

from fermdb.extract.pdf import (
    MIN_ALPHA_RATIO,
    MIN_CHARS_PER_PAGE,
    PAGE_SEPARATOR,
    PdfError,
    is_pdf,
    pdf_to_text,
)


def _pdf(pages: list[str]) -> bytes:
    """A minimal multi-page PDF whose text layer holds ``pages``."""
    objects: list[bytes] = []
    kids = " ".join(f"{4 + i * 2} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 3 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {len(objects) + 2} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF".encode()
    )
    return bytes(out)


SENTENCE = (
    "The engineered strain produced isobutanol at a titer of 22 grams per liter in "
    "shake flask fermentations after seventy two hours of cultivation on glucose medium"
)


def test_magic_bytes_decide_not_the_extension() -> None:
    assert is_pdf(b"%PDF-1.7 ...")
    assert not is_pdf(b"<?xml version='1.0'?>")
    assert not is_pdf(b"")


def test_a_real_text_layer_comes_out() -> None:
    text = pdf_to_text(_pdf([SENTENCE]))
    assert "isobutanol" in text
    assert "22 grams per liter" in text


def test_pages_are_separated_stably() -> None:
    """Page boundaries stay visible and stay put: every span is an offset into this string."""
    text = pdf_to_text(_pdf([SENTENCE, SENTENCE]))
    assert text.count(PAGE_SEPARATOR) == 1


def test_extraction_is_deterministic() -> None:
    """A quote verified today must resolve tomorrow. Same bytes, same string, every call."""
    data = _pdf([SENTENCE, SENTENCE])
    assert pdf_to_text(data) == pdf_to_text(data) == pdf_to_text(data)


def test_offsets_into_the_result_are_usable_as_spans() -> None:
    """What the whole atlas does with this text: slice it and expect the quote back."""
    text = pdf_to_text(_pdf([SENTENCE]))
    start = text.index("isobutanol")
    assert text[start : start + len("isobutanol")] == "isobutanol"


# --------------------------------------------------------------------------- the refusals


def test_a_scanned_pdf_is_refused_rather_than_returning_nothing() -> None:
    """The failure the old blanket refusal existed to prevent, now caught specifically.

    A scan has pages and no text layer. pypdf returns empty strings and raises nothing, so
    without this check the atlas would store an empty document and a model would be asked to
    quote from it.
    """
    with pytest.raises(PdfError, match="no usable text layer"):
        pdf_to_text(_pdf(["", "", ""]))


def test_a_nearly_empty_text_layer_is_refused() -> None:
    """Below the per-page floor: a few stray glyphs are not an extraction."""
    with pytest.raises(PdfError, match=str(MIN_CHARS_PER_PAGE)):
        pdf_to_text(_pdf(["a b c", "d e f"]))


def test_symbol_noise_is_refused_even_when_it_is_long_enough() -> None:
    """A broken glyph mapping produces plenty of characters, and none of them are prose.

    This is the nastier failure: it passes a length check and looks like success.
    """
    noise = " ".join(["#*%@!" * 6] * 12)
    with pytest.raises(PdfError, match="letters or digits"):
        pdf_to_text(_pdf([noise, noise]))


def test_the_alpha_threshold_admits_ordinary_scientific_prose() -> None:
    """The guard must not reject real text full of numbers, units and punctuation."""
    dense = (
        "Titers of 2.05 +/- 0.21 g/L (n=3, p<0.01) were obtained at 30 C, pH 5.0, "
        "in 15% (w/v) xylose over 72 h; yields reached 57.2 mg/g."
    ) * 3
    text = pdf_to_text(_pdf([dense]))
    assert "2.05" in text
    from fermdb.extract.pdf import _alpha_ratio

    assert _alpha_ratio(text) >= MIN_ALPHA_RATIO


def test_something_that_is_not_a_pdf_is_refused_by_its_bytes() -> None:
    with pytest.raises(PdfError, match="not a PDF"):
        pdf_to_text(b"<article>this is JATS, not a PDF</article>")


def test_an_unparseable_pdf_names_the_source() -> None:
    """A failure has to say which paper failed, or a batch run is unactionable."""
    with pytest.raises(PdfError, match="paper-under-test"):
        pdf_to_text(b"%PDF-1.4\nthis is truncated garbage", source="paper-under-test")


# --------------------------------------------------------------------------- integration


def test_load_source_text_now_reads_a_pdf(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The gap this module closed: pypdf was declared for this and nothing imported it."""
    from fermdb.config import Settings
    from fermdb.db import open_db
    from fermdb.extract.harness import load_source_text

    monkeypatch.setenv("FERMDB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FERMDB_DB_FILE", str(tmp_path / "data" / "fermdb.sqlite3"))
    settings = Settings.load()
    conn = open_db(settings.db_file)
    try:
        relative = "fulltext/aa/paper.pdf"
        target = settings.data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_pdf([SENTENCE]))
        conn.execute(
            "INSERT INTO publication (id, zone, evidence, confidence) "
            "VALUES ('YAA:PUB:pdf', 'R', 'test', 'high')"
        )
        conn.execute(
            "INSERT INTO fulltext_asset (id, publication_id, doi, oa_status, resolved_via, "
            "storage_state, content_path, checksum_sha256, source_url, media_type, retrieved_at, "
            "zone) VALUES ('YAA:FTA:pdf', 'YAA:PUB:pdf', '10.1/p', 'closed', 'none', "
            "'stored_fulltext', ?, 'sha', 'file://x', 'application/pdf', "
            "'2026-09-21T00:00:00Z', 'R')",
            (relative,),
        )
        conn.commit()
        text, _ = load_source_text(conn, settings, publication_id="YAA:PUB:pdf")
        assert "isobutanol" in text
    finally:
        conn.close()
