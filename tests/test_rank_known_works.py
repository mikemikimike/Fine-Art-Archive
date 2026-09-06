"""Tests for the display-worthiness ranking CLI."""

from __future__ import annotations

import json

import pytest
from scripts import _paths
from scripts import rank_known_works as cli

from fine_art_archive.known_works.fetchers import KnownWork


def _kw(title: str, **kw) -> KnownWork:
    return KnownWork(title=title, **kw)


def test_gather_merges_and_dedupes(monkeypatch) -> None:
    monkeypatch.setattr(
        cli, "fetch_wikidata_sparql", lambda q: [_kw("Irises", year=1889, sitelinks=20)]
    )
    monkeypatch.setattr(
        cli, "fetch_wikipedia_list", lambda n: [_kw("Irises", year=1889, image_url="http://x")]
    )
    monkeypatch.setattr(cli, "fetch_met", lambda n: [])

    works = cli.gather("Q5582", "Vincent van Gogh")

    assert len(works) == 1  # deduped across sources
    assert works[0].sitelinks == 20 and works[0].image_url == "http://x"  # metadata merged


def test_gather_needs_a_source() -> None:
    assert cli.gather(None, None) == []


def test_missing_only_drops_held_works(monkeypatch, tmp_path, capsys) -> None:
    import json

    # archive already holds one work by QID and one by title
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "meta.json").write_text(
        json.dumps({"stable_identifiers": {"wikidata_q": "Q100"}, "title": "Held By Qid"}),
        encoding="utf-8",
    )
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "meta.json").write_text(
        json.dumps({"title": "Held By Title"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        cli,
        "fetch_wikidata_sparql",
        lambda q: [
            _kw("Held By Qid", source_ids={"wikidata": "Q100"}, sitelinks=5),
            _kw("Held By Title", sitelinks=5),
            _kw("Not Held", sitelinks=5, image_url="http://x"),
        ],
    )
    monkeypatch.setattr(cli, "fetch_wikipedia_list", lambda n: [])
    monkeypatch.setattr(cli, "fetch_met", lambda n: [])

    rc = cli.main(["--artist-qid", "Q1", "--missing-only", "--staging-dir", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Not Held" in out
    assert "Held By Qid" not in out
    assert "Held By Title" not in out


def test_is_held_matches_qid_and_title() -> None:
    held_qids, held_titles = {"Q100"}, {cli._norm_title("Held By Title")}
    assert cli.is_held(_kw("x", source_ids={"wikidata": "Q100"}), held_qids, held_titles)
    assert cli.is_held(_kw("Held By Title!"), held_qids, held_titles)
    assert not cli.is_held(
        _kw("Brand New", source_ids={"wikidata": "Q999"}), held_qids, held_titles
    )


@pytest.mark.parametrize("root_source", ["works", "staging", "both", "canonical", "explicit"])
def test_missing_only_resolves_sidecar_root(root_source, monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.delenv("FAA_WORKS_DIR", raising=False)
    monkeypatch.delenv("FAA_STAGING_DIR", raising=False)
    canonical = tmp_path / "canonical"
    monkeypatch.setattr(_paths, "DEFAULT_ART_WORKS_ROOT", canonical)
    roots = {name: tmp_path / name for name in ["works", "staging", "canonical", "explicit"]}
    for name, root in roots.items():
        root.mkdir()
        (root / "meta.json").write_text(json.dumps({"title": f"Held in {name}"}), encoding="utf-8")

    if root_source in {"works", "both", "explicit"}:
        monkeypatch.setenv("FAA_WORKS_DIR", str(roots["works"]))
    if root_source in {"staging", "both", "explicit"}:
        monkeypatch.setenv("FAA_STAGING_DIR", str(roots["staging"]))
    monkeypatch.setattr(
        cli, "fetch_wikidata_sparql", lambda q: [_kw(f"Held in {name}") for name in roots]
    )
    args = ["--artist-qid", "Q5582", "--missing-only"]
    if root_source == "explicit":
        args.extend(["--staging-dir", str(roots["explicit"])])

    assert cli.main(args) == 0
    output = capsys.readouterr().out
    selected = "works" if root_source == "both" else root_source
    for name in roots:
        assert (f"Held in {name}" in output) == (name != selected)
    assert "3 works" in output


@pytest.mark.parametrize("explicit", [False, True], ids=["default", "explicit"])
@pytest.mark.parametrize("root_kind", ["missing", "file"])
def test_missing_only_rejects_unavailable_root_before_fetch(
    explicit, root_kind, monkeypatch, tmp_path, capsys
) -> None:
    """Unavailable archives must not turn every remote work into an acquisition candidate."""
    root = tmp_path / "unavailable"
    if root_kind == "file":
        root.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("FAA_WORKS_DIR", str(root))
    monkeypatch.delenv("FAA_STAGING_DIR", raising=False)

    def unexpected_fetch(*args):
        pytest.fail("invalid archive should be rejected before any remote fetch")

    monkeypatch.setattr(cli, "gather", unexpected_fetch)
    args = ["--artist-qid", "Q5582", "--missing-only"]
    if explicit:
        args.extend(["--staging-dir", str(root)])

    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert str(root) in output.err
    assert "--missing-only requires an existing sidecar directory" in output.err
    assert "--staging-dir" in output.err
    assert "FAA_WORKS_DIR, then FAA_STAGING_DIR" in output.err


def test_load_held_reads_qids_and_titles(tmp_path) -> None:
    import json

    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "meta.json").write_text(
        json.dumps({"stable_identifiers": {"wikidata_q": "Q7"}, "title": "The Night Watch"}),
        encoding="utf-8",
    )
    qids, titles = cli.load_held(tmp_path)
    assert qids == {"Q7"}
    assert cli._norm_title("The Night Watch") in titles


def test_main_ranks_and_respects_top(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "fetch_wikidata_sparql",
        lambda q: [
            _kw("Obscure Study", sitelinks=0),
            _kw("Famous", sitelinks=50, image_url="http://x", holder="MoMA"),
        ],
    )
    monkeypatch.setattr(cli, "fetch_wikipedia_list", lambda n: [])
    monkeypatch.setattr(cli, "fetch_met", lambda n: [])

    rc = cli.main(["--artist-qid", "Q5582", "--top", "1"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Famous" in out
    assert "Obscure Study" not in out  # trimmed by --top 1 (Famous ranks first)
