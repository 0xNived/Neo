import pytest

from neo.organizer.references import normalize_references


def test_reference_bundle_accepts_remote_context_and_local_path():
    references = normalize_references(
        [
            {
                "type": "document",
                "value": "https://example.com/plan.pdf",
                "label": "Plan",
                "note": "Read before Friday",
            },
            {
                "type": "local_path",
                "value": r"N:\Programming\neo\docs\architecture.md",
                "label": "Neo architecture",
            },
        ]
    )

    assert references[0]["type"] == "document"
    assert references[1]["value"].startswith("N:\\")


@pytest.mark.parametrize("reference", [{"type": "local_path", "value": "notes/today.md"}, {"type": "image", "value": "file:///private.png"}])
def test_reference_bundle_rejects_unsafe_or_ambiguous_values(reference):
    with pytest.raises(ValueError):
        normalize_references([reference])
