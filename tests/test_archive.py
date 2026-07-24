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


# --------------------------------------------------------------------------- #
# new-batch extension (frozen split)
# --------------------------------------------------------------------------- #
def _folder_inv(d, title, files):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{title}.json"), "w") as fh:
        json.dump({"folder": title, "id": f"fid-{title}", "files": files}, fh)


def _wb_file(name, size=100, sub="Crash Analysis"):
    return {"path": f"{sub}/{name}", "id": f"id-{name}", "name": name,
            "mimeType": "sheet", "size": size}


def test_load_folder_inventories_merges_and_preserves_odd_wo(tmp_path):
    from safety_eval.archive import load_folder_inventories

    d = str(tmp_path / "ninv")
    _folder_inv(d, "WO-41000069819 06-15-36512 (W-5601DF)",
                [_wb_file("Section Evaluation Workbook - 06-15-36512.xlsx")])
    _folder_inv(d, "WO-41000069819 06-21-63348 (SS-6006AS)",
                [_wb_file("Section Evaluation Workbook - 06-21-63348.xlsx"),
                 {"path": "Notes", "id": "f", "name": "Notes",
                  "mimeType": "application/vnd.google-apps.folder",
                  "size": None},
                 _wb_file("~$lockfile.xlsx", 165)])
    _folder_inv(d, "WO-410000749019 06-16-39083",
                [_wb_file("Section Evaluation Workbook - 06-16-39083.xlsx")])

    merged = load_folder_inventories(d)
    assert set(merged) == {"41000069819", "410000749019"}
    both = merged["41000069819"]
    assert both.get("split_folders") and len(both["folder_ids"]) == 2
    # folders and ~$ lock files are dropped
    names = [f["title"] for f in both["files"]]
    assert "Notes" not in names and not any(n.startswith("~$") for n in names)


def test_extend_manifest_freezes_existing_split(tmp_path):
    from safety_eval.archive import extend_manifest

    out = str(tmp_path / "archive")
    os.makedirs(out)
    existing = [
        {"wo": "41000000001", "split": "train", "analysis_type": "section",
         "countermeasure_family": "rumble-strips"},
        {"wo": "41000000002", "split": "verify", "analysis_type": "section",
         "countermeasure_family": "rumble-strips"},
        {"wo": "41000000003", "split": "verify", "analysis_type": "section",
         "countermeasure_family": "rumble-strips"},
    ]
    with open(os.path.join(out, "manifest.jsonl"), "w") as fh:
        for rec in existing:
            fh.write(json.dumps(rec) + "\n")

    d = str(tmp_path / "ninv")
    _folder_inv(d, "WO-41000000010 01-20-100",
                [_wb_file("Section Evaluation Workbook - Rumble Strips "
                          "01-20-100.xlsx")])
    summary = extend_manifest(d, str(tmp_path / "noemails"), out)

    recs = {json.loads(l)["wo"]: json.loads(l)
            for l in open(os.path.join(out, "manifest.jsonl"))}
    # existing assignments byte-frozen
    for rec in existing:
        assert recs[rec["wo"]]["split"] == rec["split"]
    # the stratum had train=1 verify=2, so the new WO balances to train
    assert recs["41000000010"]["split"] == "train"
    assert summary["added"] == ["41000000010"]
    assert os.path.exists(os.path.join(out, "meta", "41000000010.yaml"))


def test_stray_workbook_flagged(tmp_path):
    from safety_eval.archive import extend_manifest

    out = str(tmp_path / "archive")
    os.makedirs(out)
    open(os.path.join(out, "manifest.jsonl"), "w").close()
    d = str(tmp_path / "ninv")
    _folder_inv(d, "WO-41000075960 10-19-230 (SS-6010I)",
                [_wb_file("Intersection Evaluation Workbook - 10-19-230 "
                          "(SS-6010I).xlsx"),
                 _wb_file("Section Evaluation Workbook - 13-18-210 "
                          "(SS-4913CX).xlsm", size=14973781)])
    extend_manifest(d, str(tmp_path / "noemails"), out)
    rec = json.loads(open(os.path.join(out, "manifest.jsonl")).readline())
    assert "stray-workbook" in rec["flags"]
    wb_names = [f["path"] for f in rec["files"]["workbooks"]]
    assert not any("13-18-210" in n for n in wb_names)
    assert rec["analysis_type"] == "intersection"


def test_folder_title_typo_keeps_workbook(tmp_path):
    """When NO workbook matches the folder code, the folder title is the
    suspect part (WO-41000073336 titled 02-17-43501, workbook 02-17-45301):
    keep the workbook, flag the mismatch, do not strand the evaluation."""
    from safety_eval.archive import extend_manifest

    out = str(tmp_path / "archive")
    os.makedirs(out)
    open(os.path.join(out, "manifest.jsonl"), "w").close()
    d = str(tmp_path / "ninv")
    _folder_inv(d, "WO-41000073336 02-17-43501",
                [_wb_file("Section Evaluation Workbook - 02-17-45301.xlsx")])
    extend_manifest(d, str(tmp_path / "noemails"), out)
    rec = json.loads(open(os.path.join(out, "manifest.jsonl")).readline())
    assert "folder-project-mismatch" in rec["flags"]
    assert "stray-workbook" not in rec["flags"]
    assert len(rec["files"]["workbooks"]) == 1
    assert rec["analysis_type"] == "section"
