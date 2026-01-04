"""Project-wide pytest configuration helpers."""

from types import SimpleNamespace

import pytest


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_collectstart(collector):
    """Add a dummy obj attribute to Package collectors for pytest-asyncio."""
    package_type = getattr(pytest, "Package", None)
    if package_type and isinstance(collector, package_type) and not hasattr(collector, "obj"):
        collector.obj = SimpleNamespace()
    yield
