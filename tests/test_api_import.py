"""API import and route registration regression tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))


def test_api_imports_with_job_and_voice_routes_registered():
    from app.main import app

    paths = {route.path for route in app.routes}

    assert "/jobs" in paths
    assert "/voices" in paths
