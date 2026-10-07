import pytest

from glasshaus.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("https://a.example, https://b.example", ["https://a.example", "https://b.example"]),
        ('["https://a.example"]', ["https://a.example"]),
    ],
)
def test_csv_lists_from_env(monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]) -> None:
    monkeypatch.setenv("GLASSHAUS_CORS_ORIGINS", raw)
    assert Settings(_env_file=None).cors_origins == expected
