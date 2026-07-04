"""Config layer — the stdlib dotenv parser + loader (precedence, no-op)."""

from datavibes.config.dotenv import load_dotenv, parse_dotenv


def test_parse_handles_comments_quotes_blanks_and_export():
    text = "\n".join(
        [
            "# a comment",
            "",
            "NCEI_TOKEN=plain-value",
            'QUOTED="with spaces"',
            "SINGLE='single'",
            "export EXPORTED=yes",
            "HASH_VALUE=abc#123",  # inline '#' is part of the value (not a comment)
            "no_equals_line_ignored",
        ]
    )
    parsed = parse_dotenv(text)
    assert parsed == {
        "NCEI_TOKEN": "plain-value",
        "QUOTED": "with spaces",
        "SINGLE": "single",
        "EXPORTED": "yes",
        "HASH_VALUE": "abc#123",
    }


def test_load_does_not_overwrite_real_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("NCEI_TOKEN=from-dotenv\nNEW_KEY=new\n", encoding="utf-8")
    environ = {"NCEI_TOKEN": "from-real-env"}
    load_dotenv(env_file, environ=environ)
    # Real env wins; only the previously-absent key is added.
    assert environ["NCEI_TOKEN"] == "from-real-env"
    assert environ["NEW_KEY"] == "new"


def test_load_override_true_replaces(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("K=from-dotenv\n", encoding="utf-8")
    environ = {"K": "old"}
    load_dotenv(env_file, override=True, environ=environ)
    assert environ["K"] == "from-dotenv"


def test_missing_file_is_noop(tmp_path):
    environ = {"K": "keep"}
    assert load_dotenv(tmp_path / "nope.env", environ=environ) == {}
    assert environ == {"K": "keep"}
