from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from fine_art_archive.crosswalk import emit_crosswalks, to_dublin_core, to_linked_art


def _sidecar() -> dict[str, Any]:
    return {
        "work_id": "4f3a2b8-after-the-bullfight-cassatt",
        "schema_version": "1.0",
        "artist": {
            "name": "Mary Cassatt",
            "wikidata_q": "Q173223",
            "ulan": "500030502",
        },
        "title": "After the Bullfight",
        "year": "1873",
        "medium": "Oil on canvas",
        "holder": {
            "name": "Art Institute of Chicago",
            "wikidata_q": "Q239303",
            "accession": "1969.332",
            "url": "https://www.artic.edu/artworks/61446",
        },
        "rights": {
            "status": "public-domain",
            "evidence_url": "https://www.artic.edu/artworks/61446",
        },
        "stable_identifiers": {
            "wikidata_q": "Q98549878",
            "museum_accession": "1969.332",
        },
        "files": {
            "master": {
                "filename": "master.jpeg",
                "sha256": "4f3a2b8" + ("0" * 57),
                "size_bytes": 12378451,
                "ingested_at": "2026-05-16T21:30:00Z",
                "dimensions_px": [640, 825],
            },
        },
        "history": [
            {"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"},
        ],
    }


def test_dublin_core_projection_populates_core_terms() -> None:
    dc = to_dublin_core(_sidecar())

    assert dc == {
        "title": "After the Bullfight",
        "creator": "Mary Cassatt",
        "date": "1873",
        "medium": "Oil on canvas",
        "rights": "public-domain",
        "identifier": [
            "4f3a2b8-after-the-bullfight-cassatt",
            "https://www.wikidata.org/entity/Q98549878",
            "1969.332",
        ],
    }


def test_rights_projection_uses_evidence_url_when_status_missing() -> None:
    meta = _sidecar()
    meta["rights"] = {"evidence_url": "https://example.test/source"}

    assert to_dublin_core(meta)["rights"] == "https://example.test/source"
    assert to_linked_art(meta)["subject_to"] == [
        {"type": "Right", "_label": "https://example.test/source"}
    ]


def test_linked_art_projection_has_valid_context_type_and_identifiers() -> None:
    linked = to_linked_art(_sidecar())

    assert linked["@context"] == "https://linked.art/ns/v1/linked-art.json"
    assert linked["type"] == "HumanMadeObject"
    assert linked["id"] == "https://www.wikidata.org/entity/Q98549878"
    assert linked["_label"] == "After the Bullfight"
    assert linked["produced_by"]["carried_out_by"][0]["id"] == (
        "https://www.wikidata.org/entity/Q173223"
    )
    assert linked["current_owner"][0]["id"] == "https://www.wikidata.org/entity/Q239303"
    identifiers = linked["identified_by"]
    assert {
        "type": "Identifier",
        "content": "https://www.wikidata.org/entity/Q98549878",
        "id": "https://www.wikidata.org/entity/Q98549878",
    } in identifiers
    assert {"type": "Identifier", "content": "1969.332"} in identifiers


def test_emit_crosswalks_writes_dc_and_linked_art_json(tmp_path: Path) -> None:
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(_sidecar()), encoding="utf-8")

    dc_path, linked_path = emit_crosswalks(meta_path)

    assert dc_path == tmp_path / "dc.json"
    assert linked_path == tmp_path / "linkedart.json"
    assert json.loads(dc_path.read_text(encoding="utf-8"))["title"] == "After the Bullfight"
    assert json.loads(linked_path.read_text(encoding="utf-8"))["type"] == "HumanMadeObject"


@pytest.mark.parametrize("raw_qid", [None, "Q173223"])
def test_linked_art_actor_uses_canonical_artist_qid(raw_qid: str | None) -> None:
    meta = _sidecar()
    meta["artist"] = {"name": "Vincent van Gogh", "canonical": {"wikidata_q": "Q5582"}}
    if raw_qid is not None:
        meta["artist"]["wikidata_q"] = raw_qid
    original = deepcopy(meta)

    actor = to_linked_art(meta)["produced_by"]["carried_out_by"][0]

    assert actor == {
        "type": "Actor",
        "_label": "Vincent van Gogh",
        "id": "https://www.wikidata.org/entity/Q5582",
        "identified_by": [
            {"type": "Name", "content": "Vincent van Gogh"},
            {
                "type": "Identifier",
                "content": "https://www.wikidata.org/entity/Q5582",
                "id": "https://www.wikidata.org/entity/Q5582",
            },
        ],
    }
    assert meta == original


@pytest.mark.parametrize("canonical", [None, {}, {"wikidata_q": ""}, {"wikidata_q": "bad"}])
def test_linked_art_actor_falls_back_to_raw_artist_qid(canonical: Any) -> None:
    meta = _sidecar()
    meta["artist"]["canonical"] = canonical

    actor = to_linked_art(meta)["produced_by"]["carried_out_by"][0]

    assert actor["id"] == "https://www.wikidata.org/entity/Q173223"


@pytest.mark.parametrize("canonical", [None, {}, {"wikidata_q": "bad"}])
def test_linked_art_actor_without_valid_qid_keeps_name(canonical: Any) -> None:
    meta = _sidecar()
    meta["artist"] = {"name": "Unknown artist", "canonical": canonical}

    actor = to_linked_art(meta)["produced_by"]["carried_out_by"][0]

    assert actor == {
        "type": "Actor",
        "_label": "Unknown artist",
        "identified_by": [{"type": "Name", "content": "Unknown artist"}],
    }


def test_emit_crosswalks_preserves_canonical_artist_identifier(tmp_path: Path) -> None:
    meta = _sidecar()
    meta["artist"]["canonical"] = {"wikidata_q": "Q5582"}
    del meta["artist"]["wikidata_q"]
    meta_path = tmp_path / "meta.json"
    original = json.dumps(meta)
    meta_path.write_text(original, encoding="utf-8")

    dc_path, linked_path = emit_crosswalks(meta_path)

    linked = json.loads(linked_path.read_text(encoding="utf-8"))
    assert linked["produced_by"]["carried_out_by"][0]["id"] == (
        "https://www.wikidata.org/entity/Q5582"
    )
    assert json.loads(dc_path.read_text(encoding="utf-8")) == to_dublin_core(meta)
    assert meta_path.read_text(encoding="utf-8") == original
