# SPDX-License-Identifier: CC0-1.0

"""
Shared fixtures for the Open Know-How addon tests.

Nothing here imports FreeCAD. The core of the addon is deliberately free of it,
and `pixi run test-core` runs these tests in an environment that has no FreeCAD
at all, so an accidental import fails loudly instead of passing by luck.
"""

import copy
import importlib.resources
import json
import os
import urllib.error
import urllib.request

import pytest
import yaml

from freecad.OpenKnowHowMetadata.okh import schema as okh_schema

UPSTREAM_URL = (
    "https://raw.githubusercontent.com/iop-alliance/OpenKnowHow/master/src/schema/okh.schema.json"
)

# The same file load() reaches for when it is given no path.
SCHEMA_FILE = (
    importlib.resources.files("freecad.OpenKnowHowMetadata") / "resources" / "okh_schema.yaml"
)


@pytest.fixture(scope="session")
def schema():
    """The addon's schema, loaded through the loader that is under test."""
    return okh_schema.load()


@pytest.fixture(scope="session")
def raw_schema():
    """The schema as plain YAML data, for tests that need to damage it on purpose."""
    return yaml.safe_load(SCHEMA_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def upstream():
    """
    The normative Open Know-How JSON Schema.

    Downloaded, never vendored: it is AGPL-3.0-or-later and this addon is CC0.
    Set OKH_UPSTREAM_SCHEMA to a local copy to work offline, or OKH_REQUIRE_UPSTREAM=1
    to make an unreachable upstream a failure rather than a skip. CI should do the latter.
    """
    local = os.environ.get("OKH_UPSTREAM_SCHEMA")
    try:
        if local:
            with open(local, encoding="utf-8") as handle:
                return json.load(handle)
        with urllib.request.urlopen(UPSTREAM_URL, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        if os.environ.get("OKH_REQUIRE_UPSTREAM") == "1":
            pytest.fail(f"could not fetch upstream schema: {error}")
        pytest.skip(f"upstream unreachable ({error})")


@pytest.fixture
def damaged_schema(tmp_path, raw_schema):
    """
    Returns a factory: hand it a function that breaks a copy of the schema data,
    and it writes the result to a temporary file and gives you the path.
    """

    def write(damage):
        data = copy.deepcopy(raw_schema)
        damage(data)
        path = tmp_path / "okh_schema.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    return write
