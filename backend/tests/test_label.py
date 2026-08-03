from backend.graph.label import parse_label

# All prior sanitize_label tests are removed -- the request shape changed from
# "ask for prose, post-process the response" to "ask for JSON, parse a field."
# The old tests covered first-line/last-line extraction, a reasoning-marker
# blocklist, and sentence counting -- none of that logic exists anymore, so
# none of those tests carry over. parse_label gets a fresh test suite below.


def test_parse_label_clean_json():
    assert parse_label('{"label":"Diffusion LM Safety"}') == "Diffusion LM Safety"


def test_parse_label_json_wrapped_in_stray_prose():
    text = 'Sure: {"label":"X"} hope that helps'
    assert parse_label(text) == "X"


def test_parse_label_fenced_code_block():
    text = '```json\n{"label":"X"}\n```'
    assert parse_label(text) == "X"


def test_parse_label_fenced_code_block_no_json_tag():
    text = '```\n{"label":"X"}\n```'
    assert parse_label(text) == "X"


def test_parse_label_invalid_truncated_json_returns_none():
    assert parse_label('{"label":"Diff') is None


def test_parse_label_empty_label_returns_none():
    assert parse_label('{"label":""}') is None


def test_parse_label_missing_label_key_returns_none():
    assert parse_label('{"foo":"bar"}') is None


def test_parse_label_over_length_returns_none():
    long_label = "x" * 70
    assert parse_label(f'{{"label":"{long_label}"}}') is None


def test_parse_label_non_string_label_returns_none():
    assert parse_label('{"label":123}') is None


def test_parse_label_empty_input_returns_none():
    assert parse_label("") is None
    assert parse_label("   ") is None


def test_parse_label_not_json_at_all_returns_none():
    assert parse_label("just some prose with no braces at all") is None
