# tests/conftest.py
import sys
import os
import json
import pytest

# Ensure the project root is on sys.path for all test imports
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(scope="session")
def mall_data():
    """Load mall_data.json once for the entire test session."""
    data_path = os.path.join(ROOT, "mall_data.json")
    with open(data_path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def graph(mall_data):
    """Build the NetworkX graph once for the entire test session."""
    from navigation import build_graph
    return build_graph(mall_data)
