"""Cheap checks that the design mockups stay consistent (no browser needed)."""
import re
from pathlib import Path

DESIGN = Path(__file__).resolve().parents[2] / "docs" / "design"


def test_readme_states_have_screenshots():
    readme = (DESIGN / "README.md").read_text()
    names = set(re.findall(r"`((?:m-)?[a-z-]+)`", readme.split("## States", 1)[1].split("## UI", 1)[0]))
    names = {n for n in names if n in {
        "idle", "streaming", "answer", "answer-drawer", "abstain", "paused", "busy", "resetting", "failed",
        "approval-diff", "approval-resolved", "approval-empty", "trace-done", "trace-streaming",
        "trace-abstain", "trace-failed"}}
    assert len(names) == 16
    for name in names:
        for device in ("desktop", "mobile"):
            for theme in ("light", "dark"):
                assert (DESIGN / "screens" / f"{device}-{theme}-{name}.png").exists(), (device, theme, name)


def test_tokens_define_both_themes_for_used_variables():
    tokens = (DESIGN / "tokens.css").read_text()
    assert 'prefers-color-scheme: dark' in tokens and ':root[data-theme="dark"]' in tokens
    css = (DESIGN / "base.css").read_text()
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", tokens))
    local = {"--i"}  # per-step index set inline
    assert not (used - defined - local), used - defined - local
    dark_block = tokens.split(':root[data-theme="dark"]', 1)[1]
    color_vars = {v for v in defined if v.startswith(("--bg", "--surface", "--text", "--accent", "--btn", "--warn", "--danger"))}
    for v in color_vars:
        assert f"{v}:" in dark_block, v


def test_no_external_resources():
    for f in DESIGN.glob("*.html"):
        text = f.read_text()
        assert not re.search(r'(?:src|href)="https?://', text), f.name
