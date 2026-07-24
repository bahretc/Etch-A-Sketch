"""Archive manifest tests: inventory merging, meta classification, companion
clustering via shared assignment emails, deterministic stratified split, and
missing-piece flags."""
import json
import os

from email.message import EmailMessage

import pytest

from safety_eval.archive import (assign_split, build_manifest, build_meta,
                                 classify_family, companion_clusters,
                                 load_inventories)

EMAIL_BODY = """Below are assumptions for Assignment #22 and #23.

Assignment #22

*\tOrder ID: 41000075552
*\tProject ID: 02-20-61721 (TIP #SS-6002M)
*\tLocation: US 13 between the Wayne County Line and NC 58 (MP 0.00 to MP 7.38; 7.38 miles)
*\tCounty/Division: Greene County / Division 2
*\tCountermeasure: Install sinusoidal centerline rumble strips
*\tProject Completion: 10/16/2021 (construction began 5/26/2021)

Assignment #23

*\tOrder ID: 41000078043
*\tProject ID: 02-20-62355 (TIP #SS-6002AS)
*\tLocation: US 13 at SR 1132 (Shine Road/Free Gospel Road)
*\tCounty/Division: Greene County/Division 2
*\tSignal ID: 02-0240
*\tCountermeasure: Revise the existing static flashers to a VEWF system
*\tProject Completion: 2/3/2022 (construction began 12/15/2021)
"""


def _inv(tmp_path, name, title, files):
    d = tmp_path / "inv"
    d.mkdir(exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps({
        "folder_id": f"fid-{name}", "title": title, "files": files}))
    return str(d)


def _email(tmp_path, wo, body=EMAIL_BODY):
    d = tmp_path / "emails"
    d.mkdir(exist_ok=True)
    msg = EmailMessage()
    msg["Subject"] = "Assignment #22 & 23"
    msg.set_content(body)
    (d / f"{wo}__assignment.eml").write_bytes(bytes(msg))
    return str(d)


WB = {"path": "Crash Analysis/Section Evaluation Workbook - X.xlsx",
      "id": "wb1", "title": "Section Evaluation Workbook - X.xlsx",
      "mime": "x", "size": 1}
PDF = {"path": "Complete Eval.pdf", "id": "p1",
       "title": "Complete Eval.pdf", "mime": "x", "size": 1}


def test_classify_family_order():
    assert classify_family("Install rumble strips and markings") == "rumble-strips"
    assert classify_family("Revise flashers to a VEWF system") == "flashers-vewf"
    assert classify_family("Convert to all-way stop control") == "awsc"
    assert classify_family("mystery") == "other"


def test_split_folders_merge(tmp_path):
    inv_dir = _inv(tmp_path, "41000078044_1of2",
                   "WO-41000078044 (1 of 2)", [WB])
    _inv(tmp_path, "41000078044_2of2", "WO-41000078044 (2 of 2)", [PDF])
    merged = load_inventories(inv_dir)
    assert list(merged) == ["41000078044"]
    assert len(merged["41000078044"]["files"]) == 2
    meta = build_meta("41000078044", merged["41000078044"], str(tmp_path))
    assert "split-folders-merged" in meta.flags
    assert meta.analysis_type == "section"      # from the workbook filename


def test_meta_from_email_and_flags(tmp_path):
    inv_dir = _inv(tmp_path, "41000075552",
                   "WO-41000075552 02-20-61721 (SS-6002M)", [WB, PDF])
    emails = _email(tmp_path, "41000075552")
    merged = load_inventories(inv_dir)
    meta = build_meta("41000075552", merged["41000075552"], emails)
    assert meta.project_id == "02-20-61721"
    assert meta.tip == "SS-6002M"
    assert meta.county == "Greene" and meta.division == "2"
    assert meta.countermeasure_family == "rumble-strips"
    assert meta.completed == 2021
    assert meta.analysis_type == "section"
    assert "no-workbook" not in meta.flags
    # a thin folder gets flagged, never silently skipped
    inv_dir2 = _inv(tmp_path, "41000099999", "WO-41000099999 bare", [])
    meta2 = build_meta("41000099999",
                       load_inventories(inv_dir2)["41000099999"],
                       emails)
    assert "empty-folder" in meta2.flags
    assert "no-workbook" in meta2.flags
    assert "no-assignment-email" in meta2.flags


def test_companions_share_split(tmp_path):
    inv_dir = _inv(tmp_path, "41000075552",
                   "WO-41000075552 02-20-61721 (SS-6002M)", [WB])
    _inv(tmp_path, "41000078043",
         "WO-41000078043 02-20-62355 (SS-6002AS)", [WB])
    _inv(tmp_path, "41000064924", "WO-41000064924 14-19-218", [WB])
    # the email under 75552 names 78043's order id: one thread, one cluster
    emails = _email(tmp_path, "41000075552")
    merged = load_inventories(inv_dir)
    metas = {wo: build_meta(wo, inv, emails) for wo, inv in merged.items()}
    clusters = companion_clusters(metas, emails)
    assert {"41000075552", "41000078043"} in clusters
    assign_split(metas, clusters)
    assert metas["41000075552"].split == metas["41000078043"].split
    assert metas["41000078043"].companions == ["41000075552"]
    assert metas["41000064924"].split in ("train", "verify")


def test_split_deterministic_and_balanced(tmp_path):
    inv_dir = None
    for i in range(10):
        wo = f"410000{70000 + i}"
        inv_dir = _inv(tmp_path, wo, f"WO-{wo} 01-01-{i}", [WB])
    merged = load_inventories(inv_dir)
    emails = str(tmp_path / "none")
    metas = {wo: build_meta(wo, inv, emails) for wo, inv in merged.items()}
    clusters = companion_clusters(metas, emails)
    assign_split(metas, clusters)
    first = {wo: m.split for wo, m in metas.items()}
    counts = list(first.values())
    assert counts.count("train") == 5 and counts.count("verify") == 5
    # re-running assigns identically (docs/10: assigned once, stable)
    metas2 = {wo: build_meta(wo, inv, emails) for wo, inv in merged.items()}
    assign_split(metas2, companion_clusters(metas2, emails))
    assert {wo: m.split for wo, m in metas2.items()} == first


def test_build_manifest_end_to_end(tmp_path):
    inv_dir = _inv(tmp_path, "41000075552",
                   "WO-41000075552 02-20-61721 (SS-6002M)", [WB, PDF])
    _inv(tmp_path, "41000078043",
         "WO-41000078043 02-20-62355 (SS-6002AS)", [WB, PDF])
    emails = _email(tmp_path, "41000075552")
    out = str(tmp_path / "out")
    summary = build_manifest(inv_dir, emails, out)
    assert summary["evaluations"] == 2
    assert summary["multi_wo_clusters"] == [["41000075552", "41000078043"]]
    lines = [json.loads(l) for l in
             open(os.path.join(out, "manifest.jsonl"))]
    assert len(lines) == 2
    assert all(l["split"] in ("train", "verify") for l in lines)
    assert lines[0]["split"] == lines[1]["split"]      # companions together
    assert os.path.exists(os.path.join(out, "meta", "41000075552.yaml"))
