"""docker-compose.yml must pass through every .env.example variable that is a Settings field."""
import re
from pathlib import Path

import yaml

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def _env_example_names() -> set[str]:
    names = set()
    for line in (ROOT / ".env.example").read_text().splitlines():
        m = re.match(r"#?\s*([A-Z][A-Z0-9_]+)=", line)
        if m:
            names.add(m.group(1))
    return names


def test_every_env_example_setting_is_passed_to_the_containers():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    passed = set(compose["x-backend-env"])
    fields = {f.upper() for f in Settings.model_fields}
    missing = sorted((_env_example_names() & fields) - passed)
    assert not missing, f"in .env.example and Settings but not passed through compose: {missing}"
    assert {"TRUST_PROXY_HEADERS", "DEMO_RESET_INTERVAL_H", "AUTO_SEED"} <= passed


def test_compose_defaults_match_settings_defaults_for_operational_vars():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["x-backend-env"]
    d = {k: f.default for k, f in Settings.model_fields.items()}  # not the test env's overrides
    for name in ("MAX_STREAMS_PER_IP", "MAX_PENDING_RUNS", "MAX_CONCURRENT_RUNS", "RUN_TIMEOUT_S",
                 "UNKNOWN_COST_PER_RUN_USD", "DEMO_RESET_INTERVAL_H", "DEMO_RESET_RETRY_S"):
        default = re.search(r":-([^}]*)\}", compose[name]).group(1)
        assert float(default) == float(d[name.lower()]), name
    assert re.search(r":-false\}", compose["TRUST_PROXY_HEADERS"]) and d["trust_proxy_headers"] is False
    assert re.search(r":-true\}", compose["AUTO_SEED"]) and d["auto_seed"] is True
