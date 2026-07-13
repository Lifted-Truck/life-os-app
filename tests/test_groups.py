"""Domain umbrella grouping (presentation overlay) — dashboard/groups.py."""
import yaml

from dashboard.groups import load_umbrellas, group_rows

GROUPS = {
    "umbrellas": [
        {"key": "health", "label": "Health & Body", "domains": ["fitness", "meals"]},
        {"key": "career", "label": "Career & Work", "domains": ["career", "coding"]},
    ]
}


def _write_groups(root, data):
    (root / "dev").mkdir(parents=True, exist_ok=True)
    (root / "dev" / "domain-groups.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_load_umbrellas_reads_file(tmp_path):
    _write_groups(tmp_path, GROUPS)
    ums = load_umbrellas(tmp_path)
    assert [u["label"] for u in ums] == ["Health & Body", "Career & Work"]
    assert ums[0]["domains"] == ["fitness", "meals"]


def test_missing_file_falls_back_to_single_group(tmp_path):
    ums = load_umbrellas(tmp_path)
    assert len(ums) == 1 and ums[0]["domains"] is None   # the "All domains" catch-all


def test_malformed_file_falls_back(tmp_path):
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev" / "domain-groups.yaml").write_text("umbrellas: not-a-list", encoding="utf-8")
    assert load_umbrellas(tmp_path) == [{"key": "all", "label": "All domains", "domains": None}]


def test_group_rows_partitions_in_declared_order(tmp_path):
    _write_groups(tmp_path, GROUPS)
    rows = [{"name": n} for n in ("coding", "meals", "career", "fitness")]
    groups = group_rows(rows, "name", tmp_path)
    assert [g["label"] for g in groups] == ["Health & Body", "Career & Work"]
    # declared order within a group, not input order
    assert [r["name"] for r in groups[0]["rows"]] == ["fitness", "meals"]
    assert [r["name"] for r in groups[1]["rows"]] == ["career", "coding"]


def test_ungrouped_domain_lands_in_other(tmp_path):
    _write_groups(tmp_path, GROUPS)
    rows = [{"name": n} for n in ("fitness", "mystery")]
    groups = group_rows(rows, "name", tmp_path)
    assert groups[-1]["label"] == "Other"
    assert [r["name"] for r in groups[-1]["rows"]] == ["mystery"]


def test_fallback_groups_all_rows_together(tmp_path):
    rows = [{"domain": n} for n in ("a", "b", "c")]   # no groups file
    groups = group_rows(rows, "domain", tmp_path)
    assert len(groups) == 1
    assert [r["domain"] for r in groups[0]["rows"]] == ["a", "b", "c"]
