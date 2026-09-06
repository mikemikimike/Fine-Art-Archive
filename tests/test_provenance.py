"""Tests for the additive field provenance sidecar ledger."""

from __future__ import annotations

from copy import deepcopy

import jsonschema
import pytest

from fine_art_archive import provenance, sidecar

MINIMAL_VALID = {
    "work_id": "4f3a2b8-after-the-bullfight-cassatt",
    "schema_version": "1.0",
    "artist": {"name": "Mary Cassatt"},
    "title": "After the Bullfight",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "4f3a2b8" + ("0" * 57),
            "size_bytes": 12378451,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


def test_field_provenance_schema_is_additive_and_validates_entries():
    meta = deepcopy(MINIMAL_VALID)
    meta["field_provenance"] = {
        "medium": {
            "status": "available",
            "source": "museum_catalog",
            "source_ref": None,
            "checked_at": "2026-07-24T17:00:00Z",
            "note": None,
        }
    }

    sidecar.validate(meta)
    assert sidecar.is_valid(MINIMAL_VALID)


def test_invalid_field_provenance_status_fails_schema_validation():
    meta = deepcopy(MINIMAL_VALID)
    meta["field_provenance"] = {"medium": {"status": "guessed"}}

    with pytest.raises(jsonschema.ValidationError):
        sidecar.validate(meta)


def test_get_set_and_needs_research_round_trip():
    meta = deepcopy(MINIMAL_VALID)

    assert provenance.get(meta, "medium") is None
    assert provenance.needs_research(meta, "medium")

    entry = provenance.set(
        meta,
        "medium",
        "available",
        "museum_catalog",
        source_ref="https://example.test/work/1",
        checked_at="2026-07-24T17:00:00Z",
        note="Catalogued medium.",
    )

    assert provenance.get(meta, "medium") == entry
    assert not provenance.needs_research(meta, "medium")

    provenance.set(meta, "category", "unverified", "filename_backfill")
    provenance.set(meta, "dimensions_original", "not_researched", "migration")
    provenance.set(meta, "title", "not_available", "museum_catalog")
    provenance.set(meta, "artist", "conflicting", "museum_catalog")
    assert provenance.needs_research(meta, "category")
    assert provenance.needs_research(meta, "dimensions_original")
    assert provenance.needs_research(meta, "artist")
    assert not provenance.needs_research(meta, "title")

    omitted_source = provenance.set(meta, "notes", "not_researched")
    assert omitted_source["source"] is None
    assert provenance.needs_research(meta, "notes")


def test_set_rejects_unknown_status_and_stamps_timestamp():
    meta = deepcopy(MINIMAL_VALID)

    with pytest.raises(ValueError, match="unsupported provenance status"):
        provenance.set(meta, "medium", "guessed", "museum_catalog")

    entry = provenance.set(meta, "medium", "conflicting", "museum_catalog")
    assert entry["checked_at"].endswith("Z")
    assert provenance.needs_research(meta, "medium")


def test_filename_backfill_migration_marks_present_fields_without_overwriting():
    meta = deepcopy(MINIMAL_VALID)
    meta.update(
        {
            "medium": "Oil on canvas",
            "category": "painting",
            "dimensions_original": {"h_cm": 82.5, "w_cm": 64.0},
        }
    )
    original_medium = meta["medium"]
    original_category = meta["category"]
    original_dimensions = deepcopy(meta["dimensions_original"])
    provenance.set(meta, "medium", "available", "museum_catalog")

    marked = provenance.mark_filename_backfilled_fields(meta)

    assert marked == ["category", "dimensions_original"]
    assert provenance.get(meta, "medium")["status"] == "available"
    assert provenance.get(meta, "category")["status"] == "unverified"
    assert provenance.get(meta, "dimensions_original")["status"] == "unverified"
    assert meta["medium"] == original_medium
    assert meta["category"] == original_category
    assert meta["dimensions_original"] == original_dimensions


@pytest.mark.parametrize(
    ("artist", "expected"),
    [
        ({"name": "Vermeer", "canonical": {"wikidata_q": "Q41264"}}, "Q41264"),
        ({"wikidata_q": "Q41264"}, "Q41264"),
        ({"wikidata_q": "Q41264", "canonical": {"wikidata_q": "Q123"}}, "Q41264"),
        ({"wikidata_q": None, "canonical": {"wikidata_q": "Q41264"}}, "Q41264"),
        ({"wikidata_q": "", "canonical": {"wikidata_q": "Q41264"}}, "Q41264"),
        ({"name": "Vermeer"}, None),
        ({"canonical": {}}, None),
        ({"canonical": None}, None),
        ({"canonical": "Vermeer"}, None),
        ({"canonical": []}, None),
        (None, None),
        ("Vermeer", None),
    ],
)
def test_artist_qid_field_value_uses_canonical_fallback(artist, expected):
    meta = {"artist": artist}
    before = deepcopy(meta)

    assert provenance._field_value(meta, "artist_qid") == expected
    assert meta == before


def test_completeness_conflict_keeps_canonical_artist_qid_without_mutation():
    meta = deepcopy(MINIMAL_VALID)
    meta["artist"]["canonical"] = {"wikidata_q": "Q173223"}
    provenance.set(
        meta,
        "artist_qid",
        "conflicting",
        "museum_catalog",
        note='Higher-tier source replaced lower-tier existing value "Q123".',
    )
    before = deepcopy(meta)

    report = provenance.completeness_report([meta])

    assert report.total_works == 1
    artist_row = next(row for row in report.fields if row.field == "artist_qid")
    assert artist_row.count("conflicting") == 1
    assert report.conflicts == (
        provenance.Conflict(
            work_id=meta["work_id"],
            field="artist_qid",
            kept_value="Q173223",
            kept_source="museum_catalog",
            losing_value="Q123",
            losing_source=None,
            note=meta["field_provenance"]["artist_qid"]["note"],
        ),
    )
    assert meta == before
