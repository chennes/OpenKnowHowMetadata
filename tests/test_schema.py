# SPDX-License-Identifier: CC0-1.0

"""
Checks okh_schema.yaml against the upstream Open Know-How JSON Schema.

Two kinds of check:

  structural   the schema is internally consistent. Always runs.
  drift        it still agrees with upstream. Needs okh.schema.json.

Upstream is fetched over the network and never vendored: it is
AGPL-3.0-or-later and this addon is CC0.

Run:
    python tests/test_schema.py

Environment:
    OKH_UPSTREAM_SCHEMA   path to a local okh.schema.json, skips the download
    OKH_REQUIRE_UPSTREAM  set to 1 to fail rather than skip when it cannot be
                          fetched. Use this in CI.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

UPSTREAM_URL = (
    "https://raw.githubusercontent.com/iop-alliance/OpenKnowHow/master/src/schema/okh.schema.json"
)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "freecad"
    / "OpenKnowHowMetadata"
    / "resources"
    / "okh_schema.yaml"
)

# These four exist only inside the JSON Schema's conditional "allOf" rules, not
# in its "properties", so they are expected to be present here and absent there.
CONDITIONAL_FIELDS = {"material", "printing-process", "component-sides", "2d-size-mm"}

# Nested object definitions whose "required" arrays we mirror.
NESTED_REQUIRED = {
    "part": "part",
    "software": "software",
    "image": "imageObject",
    "outer-dimensions": "outerDimensions",
    "rdf": "rdfNamespace",
}

failures = []
skipped = []


def check(condition, message, detail=""):
    if not condition:
        failures.append(message + (f"\n      {detail}" if detail else ""))


def walk(fields, depth=0):
    for field in fields:
        yield depth, field
        yield from walk(field.get("children", []), depth + 1)


def load_schema():
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_upstream():
    local = os.environ.get("OKH_UPSTREAM_SCHEMA")
    if local:
        with open(local, encoding="utf-8") as handle:
            return json.load(handle)
    try:
        with urllib.request.urlopen(UPSTREAM_URL, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        if os.environ.get("OKH_REQUIRE_UPSTREAM") == "1":
            failures.append(f"could not fetch upstream schema: {error}")
        else:
            skipped.append(f"upstream unreachable ({error}); drift checks skipped")
        return None


def check_structure(schema):
    """The schema must be internally consistent, whatever upstream says."""
    vocabularies = set(schema["vocabularies"])
    constraints = {entry["id"] for entry in schema["constraints"]}
    referenced = set()
    top_level = []

    for depth, field in walk([f for g in schema["groups"] for f in g["fields"]]):
        key = field.get("key", "<unnamed>")
        for required_property in ("key", "type", "obligation", "label"):
            check(required_property in field, f"field {key!r} has no {required_property!r}")
        if depth == 0:
            top_level.append(key)
            check("tier" in field, f"top-level field {key!r} has no tier")
            check("emit" in field, f"top-level field {key!r} has no emit")
        # "agent" is polymorphic: it accepts a string or an object, so it
        # carries children describing the object form. See "forms" in the schema.
        if field.get("type") in ("object", "agent"):
            check("children" in field, f"{field.get('type')} field {key!r} has no children")
        else:
            check("children" not in field, f"non-object field {key!r} has children")
        if field.get("type") == "enum":
            check("vocabulary" in field, f"enum field {key!r} names no vocabulary")
        if "vocabulary" in field:
            check(
                field["vocabulary"] in vocabularies,
                f"field {key!r} names unknown vocabulary {field['vocabulary']!r}",
            )
        if "constraint" in field:
            referenced.add(field["constraint"])
        condition = field.get("condition", "")
        if isinstance(condition, str) and condition.startswith("constraint:"):
            referenced.add(condition.split(":", 1)[1])

    check(
        len(top_level) == len(set(top_level)),
        "duplicate top-level field keys",
        sorted({k for k in top_level if top_level.count(k) > 1}),
    )
    check(
        not (referenced - constraints),
        "field refers to a constraint that is not defined",
        sorted(referenced - constraints),
    )
    check(
        not (constraints - referenced),
        "constraint is defined but never referenced",
        sorted(constraints - referenced),
    )
    return set(top_level)


def check_drift(schema, upstream, our_fields):
    """The schema must still agree with upstream on the facts."""
    their_fields = {k for k in upstream["properties"] if k != "$schema"}
    canonical = our_fields - CONDITIONAL_FIELDS

    check(
        not (their_fields - canonical),
        "upstream has fields this schema does not define",
        sorted(their_fields - canonical),
    )
    check(
        not (canonical - their_fields),
        "this schema defines fields upstream does not have",
        sorted(canonical - their_fields),
    )

    ours_required = {
        f["key"]
        for group in schema["groups"]
        for f in group["fields"]
        if f["obligation"] == "required"
    }
    theirs_required = set(upstream["required"])
    check(
        ours_required == theirs_required,
        "top-level required set disagrees with upstream",
        f"ours={sorted(ours_required)} upstream={sorted(theirs_required)}",
    )

    by_key = {f["key"]: f for g in schema["groups"] for f in g["fields"]}
    for field_key, definition_name in NESTED_REQUIRED.items():
        theirs = set(upstream["$defs"][definition_name].get("required", []))
        ours = {
            child["key"]
            for child in by_key[field_key]["children"]
            if child["obligation"] == "required"
        }
        check(
            ours == theirs,
            f"nested required set for {field_key!r} disagrees with upstream",
            f"ours={sorted(ours)} upstream={sorted(theirs)}",
        )

    image_props = upstream["$defs"]["imageObject"]["properties"]
    expected = {
        "otrl": [o["const"] for o in upstream["properties"]["technology-readiness-level"]["oneOf"]],
        "odrl": [
            o["const"] for o in upstream["properties"]["documentation-readiness-level"]["oneOf"]
        ],
        "image_slots": image_props["slots"]["items"]["oneOf"][1]["enum"],
        "image_tags": image_props["tags"]["items"]["oneOf"][1]["enum"],
        "printing_process": upstream["allOf"][0]["then"]["properties"]["printing-process"]["enum"],
    }
    for name, theirs in expected.items():
        ours = [entry["value"] for entry in schema["vocabularies"][name]["values"]]
        check(
            sorted(ours) == sorted(theirs),
            f"vocabulary {name!r} disagrees with upstream",
            f"only ours={sorted(set(ours) - set(theirs))} "
            f"only upstream={sorted(set(theirs) - set(ours))}",
        )

    okhv = schema["spec"]["okhv"]
    check(
        okhv in upstream["properties"]["okhv"]["enum"],
        f"spec.okhv {okhv!r} is not an okhv upstream recognizes",
        f"upstream accepts {upstream['properties']['okhv']['enum']}",
    )


def main():
    schema = load_schema()
    our_fields = check_structure(schema)

    upstream = load_upstream()
    if upstream is not None:
        check_drift(schema, upstream, our_fields)

    print(f"schema:      {SCHEMA_PATH}")
    print(f"okhv:        {schema['spec']['okhv']}")
    print(f"groups:      {len(schema['groups'])}")
    print(
        f"fields:      {len(our_fields)} top level, "
        f"{len(our_fields - CONDITIONAL_FIELDS)} canonical"
    )
    print(f"vocabularies:{len(schema['vocabularies']):3d}")

    for note in skipped:
        print(f"\nSKIPPED: {note}")
    if failures:
        print(f"\n{len(failures)} FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
