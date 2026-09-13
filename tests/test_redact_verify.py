"""redact_verify: masking, oracle filtering and the verification record."""
import shutil

import pytest

from safety_eval.redact_verify import RedactionVerification, _ADDRESS_STOP, _HOUSE_NO_RE, _mask


def test_mask_never_echoes_pii():
    assert _mask("BULLARD") == "BU*****"
    assert _mask("123") == "***"
    assert len(_mask("5551234")) == 7


def test_record_summary_and_clean():
    v = RedactionVerification(pages=4, oracle_size=30)
    assert v.clean and "Verified clean" in v.summary()
    v.leaks.append((2, "name", "BU*****"))
    assert not v.clean and "1 oracle hit" in v.summary()


def test_form_vocabulary_is_stoplisted():
    for w in ("TRAILER", "NORTH", "NARRATIVE", "PAPERS", "TRAFFIC"):
        assert w in _ADDRESS_STOP
    assert _HOUSE_NO_RE.match("12260") and not _HOUSE_NO_RE.match("1234567")


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract missing")
def test_verify_synthetic_report(tmp_path):
    """A synthetic 'report' with a driver band: redaction plus verification round trip."""
    from PIL import Image, ImageDraw, ImageFont

    from safety_eval.redact import redact_file
    from safety_eval.redact_verify import verify_redaction
    img = Image.new("RGB", (1700, 2200), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 34)
    except OSError:
        f = ImageFont.load_default()
    d.text((100, 100), "NORTH CAROLINA DMV-349 CRASH REPORT   CRASH ID 108279485", font=f, fill="black")
    d.text((100, 200), "COUNTY UNION   ROUTE SR 1001 AT SR 1617", font=f, fill="black")
    d.text((100, 500), "Driver", font=f, fill="black")
    d.text((100, 545), "First Middle Last", font=f, fill="black")
    d.text((100, 590), "KAWAYNIA ZEPHYRINE BULLARDSON", font=f, fill="black")
    d.text((100, 640), "Address 12260 SANDLOT DRIVE", font=f, fill="black")
    d.text((100, 690), "Phone (910) 555-7336", font=f, fill="black")
    d.text((100, 740), "DOB 02/21/1979", font=f, fill="black")
    src = tmp_path / "report.png"
    img.save(src)
    out = tmp_path / "report_REDACTED.pdf"
    rep = redact_file(str(src), str(out))
    assert rep.boxes > 0
    v = verify_redaction(str(src), str(out))
    assert v.oracle_size > 0
    assert v.clean, (v.leaks, v.patterns)
    # control: the unredacted page must fail
    v0 = verify_redaction(str(src), str(src))
    assert not v0.clean
