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


def test_every_setting_is_documented() -> None:
    """docs/configuration.md lists every server setting and every variable in .env.example."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    doc = root / "docs" / "configuration.md"
    if not doc.exists():
        pytest.skip("not running from a full checkout")
    text = doc.read_text()
    wanted = {f"GLASSHAUS_{name.upper()}" for name in Settings.model_fields}
    wanted |= set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (root / ".env.example").read_text(), re.M))
    missing = sorted(name for name in wanted if f"`{name}`" not in text)
    assert not missing, f"add these to docs/configuration.md: {missing}"
