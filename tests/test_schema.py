# SPDX-License-Identifier: CC0-1.0

"""
Checks okh_schema.yaml, through the loader in okh/schema.py, against the upstream
Open Know-How JSON Schema.

Three kinds of check:

  loader      malformed input is rejected. Always runs.
  structural  the schema is internally consistent in ways the loader cannot see.
              Always runs.
  drift       it still agrees with upstream. Needs okh.schema.json.

Note that these tests only test things that the loader itself cannot: much of the work in this addon
is self-testing because it begins by doing a fully-validating load of the YAML file. If that file
breaks or drifts, you'll get a runtime error.

Run:
    pytest tests/           in the default environment
    pixi run test-core      in an environment with no FreeCAD, on the 3.10 floor

Environment:
    OKH_UPSTREAM_SCHEMA   path to a local okh.schema.json, skips the download
    OKH_REQUIRE_UPSTREAM  set to 1 to fail rather than skip when it cannot be
                          fetched. Use this in CI.
"""

import pytest

from freecad.OpenKnowHowMetadata.okh import schema as okh_schema
from freecad.OpenKnowHowMetadata.okh.schema import (
    ConditionKind,
    FieldType,
    Obligation,
    SchemaError,
)

# These four exist only inside the JSON Schema's conditional "allOf" rules, not in
# its "properties", so they are expected to be present here and absent there.
CONDITIONAL_FIELDS = {"material", "printing-process", "component-sides", "2d-size-mm"}

# Nested object definitions whose "required" arrays we mirror, as our field key
# against the name upstream gives the definition.
NESTED_REQUIRED = {
    "part": "part",
    "software": "software",
    "image": "imageObject",
    "outer-dimensions": "outerDimensions",
    "rdf": "rdfNamespace",
}

VOCABULARIES_WITH_UPSTREAM_EQUIVALENTS = [
    "otrl",
    "odrl",
    "image_slots",
    "image_tags",
    "printing_process",
]


def upstream_vocabulary(upstream, name):
    """The values upstream defines for one of our vocabularies."""
    images = upstream["$defs"]["imageObject"]["properties"]
    if name == "otrl":
        return [o["const"] for o in upstream["properties"]["technology-readiness-level"]["oneOf"]]
    if name == "odrl":
        return [
            o["const"] for o in upstream["properties"]["documentation-readiness-level"]["oneOf"]
        ]
    if name == "image_slots":
        return images["slots"]["items"]["oneOf"][1]["enum"]
    if name == "image_tags":
        return images["tags"]["items"]["oneOf"][1]["enum"]
    if name == "printing_process":
        return upstream["allOf"][0]["then"]["properties"]["printing-process"]["enum"]
    raise AssertionError(f"no upstream equivalent known for {name!r}")


# ---------------------------------------------------------------------------
# loader
# ---------------------------------------------------------------------------


def test_the_shipped_schema_loads(schema):
    assert schema.spec.okhv == "2.4"
    assert schema.spec.filename == "okh.toml"


def test_an_unreadable_path_is_not_a_schema_error():
    """A missing file is a file problem, not a malformed schema."""
    with pytest.raises(FileNotFoundError):
        okh_schema.load("does-not-exist.yaml")


def test_an_unexpected_schema_version_is_rejected(damaged_schema):
    def bump(data):
        data["schema_version"] = okh_schema.SCHEMA_VERSION + 1

    with pytest.raises(SchemaError, match="schema_version"):
        okh_schema.load(damaged_schema(bump))


def test_an_unknown_vocabulary_reference_is_rejected(damaged_schema):
    def misname(data):
        for group in data["groups"]:
            for field in group["fields"]:
                if field["key"] == "tsdc":
                    field["vocabulary"] = "tsdcc"

    with pytest.raises(SchemaError, match="unknown vocabulary 'tsdcc'"):
        okh_schema.load(damaged_schema(misname))


def test_an_unknown_constraint_reference_is_rejected(damaged_schema):
    def misname(data):
        for group in data["groups"]:
            for field in group["fields"]:
                if field["key"] == "part":
                    field["constraint"] = "no_such_constraint"

    with pytest.raises(SchemaError, match="unknown constraint"):
        okh_schema.load(damaged_schema(misname))


def test_an_unknown_enum_value_is_rejected(damaged_schema):
    def mistype(data):
        data["groups"][0]["fields"][0]["emit"] = "sclar"

    with pytest.raises(SchemaError, match="unknown emit 'sclar'"):
        okh_schema.load(damaged_schema(mistype))


def test_a_bare_string_where_a_list_belongs_is_rejected(damaged_schema):
    """tuple() would otherwise shred a string into one character per element."""

    def unwrap(data):
        data["constraints"][0]["children"] = "source"

    with pytest.raises(SchemaError, match="children must be a list"):
        okh_schema.load(damaged_schema(unwrap))


# ---------------------------------------------------------------------------
# structural
# ---------------------------------------------------------------------------


def test_top_level_field_keys_are_unique(schema):
    keys = [field.key for field in schema.top_level()]
    assert sorted(keys) == sorted(set(keys))


def test_field_paths_are_unique(schema):
    """Shared YAML anchors must produce separate fields, not aliases of one."""
    paths = [field.path for field in schema.walk()]
    assert len(paths) == len(set(paths))


def test_top_level_fields_have_a_tier(schema):
    """tier drives how prominent a field is in the editor, so every one needs it."""
    assert [field.key for field in schema.top_level() if field.tier is None] == []


def test_only_object_and_agent_fields_have_children(schema):
    """ "agent" is polymorphic: it accepts a string or an object, so it carries
    children describing the object form. See "forms" in the schema."""
    for field in schema.walk():
        has_children = bool(field.children)
        should = field.type in (FieldType.OBJECT, FieldType.AGENT)
        assert has_children == should, f"{'.'.join(field.path)} ({field.type.name})"


def test_enum_fields_name_a_vocabulary(schema):
    for field in schema.walk():
        if field.type is FieldType.ENUM:
            assert field.vocabulary is not None, ".".join(field.path)


def test_every_constraint_is_referenced(schema):
    """A constraint nothing points at is dead weight, and probably a rename gone wrong."""
    referenced = set()
    for field in schema.walk():
        if field.constraint is not None:
            referenced.add(field.constraint.id)
        if field.condition is not None and field.condition.kind is ConditionKind.CONSTRAINT:
            referenced.add(field.condition.argument)
    assert set(schema.constraints) == referenced


# ---------------------------------------------------------------------------
# drift
# ---------------------------------------------------------------------------


def test_field_set_matches_upstream(schema, upstream):
    theirs = {key for key in upstream["properties"] if key != "$schema"}
    ours = {field.key for field in schema.top_level()} - CONDITIONAL_FIELDS
    assert ours == theirs


def test_required_set_matches_upstream(schema, upstream):
    ours = {field.key for field in schema.top_level() if field.obligation is Obligation.REQUIRED}
    assert ours == set(upstream["required"])


@pytest.mark.parametrize(("field_key", "definition"), sorted(NESTED_REQUIRED.items()))
def test_nested_required_set_matches_upstream(schema, upstream, field_key, definition):
    theirs = set(upstream["$defs"][definition].get("required", []))
    ours = {
        child.key
        for child in schema.field(field_key).children
        if child.obligation is Obligation.REQUIRED
    }
    assert ours == theirs


@pytest.mark.parametrize("name", VOCABULARIES_WITH_UPSTREAM_EQUIVALENTS)
def test_vocabulary_matches_upstream(schema, upstream, name):
    ours = {entry.value for entry in schema.vocabularies[name].values}
    assert ours == set(upstream_vocabulary(upstream, name))


def test_okhv_is_one_upstream_recognizes(schema, upstream):
    assert schema.spec.okhv in upstream["properties"]["okhv"]["enum"]
