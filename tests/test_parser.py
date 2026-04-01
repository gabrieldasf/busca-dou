"""Tests for PDF parser CID noise stripping utilities."""

from __future__ import annotations

from src.parsers.pdf_parser import _cid_ratio, _strip_cid_noise

# --- _strip_cid_noise ---


def test_strip_cid_no_cid_present() -> None:
    text = "DECRETO No 12345 de 30 de marco de 2026"
    assert _strip_cid_noise(text) == text


def test_strip_cid_block_of_three_or_more() -> None:
    text = "(cid:1)(cid:2)(cid:3) some real content here"
    result = _strip_cid_noise(text)
    assert "(cid:" not in result
    assert "some real content here" in result


def test_strip_cid_exactly_two_not_stripped() -> None:
    """Regex requires {3,} consecutive CIDs - 2 should remain."""
    text = "(cid:10)(cid:20) some content"
    result = _strip_cid_noise(text)
    assert "(cid:10)" in result
    assert "(cid:20)" in result


def test_strip_cid_all_cid_returns_empty() -> None:
    text = "(cid:1)(cid:2)(cid:3)(cid:4)(cid:5)"
    assert _strip_cid_noise(text) == ""


def test_strip_cid_whitespace_between_cids() -> None:
    text = "(cid:1)  (cid:2)\n(cid:3)  real text follows"
    result = _strip_cid_noise(text)
    assert "(cid:" not in result
    assert "real text follows" in result


def test_strip_cid_mixed_blocks_and_content() -> None:
    text = "Header (cid:1)(cid:2)(cid:3) middle (cid:4)(cid:5)(cid:6) footer"
    result = _strip_cid_noise(text)
    assert "Header" in result
    assert "middle" in result
    assert "footer" in result
    assert "(cid:" not in result


def test_strip_cid_empty_string() -> None:
    assert _strip_cid_noise("") == ""


def test_strip_cid_trims_whitespace() -> None:
    text = "  (cid:1)(cid:2)(cid:3)  "
    assert _strip_cid_noise(text) == ""


# --- _cid_ratio ---


def test_cid_ratio_no_cids() -> None:
    assert _cid_ratio("plain text no cids") == 0.0


def test_cid_ratio_empty_string() -> None:
    assert _cid_ratio("") == 0.0


def test_cid_ratio_all_cids() -> None:
    text = "(cid:1)(cid:2)(cid:3)"
    assert _cid_ratio(text) == 1.0


def test_cid_ratio_partial() -> None:
    text = "(cid:1)hello"  # 7 + 5 = 12 chars
    ratio = _cid_ratio(text)
    assert abs(ratio - 7 / 12) < 0.01


def test_cid_ratio_multi_digit() -> None:
    text = "(cid:123)"  # 9 chars, all CID
    assert _cid_ratio(text) == 1.0
