from sprint_pulse.types_defaults import (
    PALETTE, DEFAULT_EVENT_TYPES, DEFAULT_ABSENCE_TYPES,
    DEFAULT_EVENT_KEYS, DEFAULT_ABSENCE_KEYS,
)


def test_defaults_use_palette_colors():
    for t in DEFAULT_EVENT_TYPES + DEFAULT_ABSENCE_TYPES:
        assert t["color"] in PALETTE, f'{t["key"]} color {t["color"]} not in palette'


def test_default_keys_match_legacy_values():
    assert DEFAULT_EVENT_KEYS == {"tags", "gono", "ga", "freeze", "test"}
    assert DEFAULT_ABSENCE_KEYS == {"pto", "holiday", "company", "partial", "tentative"}


def test_defaults_have_required_fields():
    for t in DEFAULT_EVENT_TYPES + DEFAULT_ABSENCE_TYPES:
        assert set(t) == {"key", "label", "abbreviation", "color", "sort_order"}
        assert 1 <= len(t["abbreviation"]) <= 2
