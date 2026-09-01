# SPDX-License-Identifier: CC0-1.0

# Representation of the Open Know-How 2.4 schema as a set of Python data structures, and a
# function to load a YAML representation of the schema into memory in a way that it can be
# traversed by the UI-builder later on.

from __future__ import annotations

import importlib.resources
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from functools import cached_property
from pathlib import Path
from types import MappingProxyType
from typing import Any

import re

import yaml

# The okh_schema.yaml layout this module understands. Bump it only when the file's structure changes
# in a way that breaks this loader. **It is unrelated to spec.okhv**, which is the version of the
# Open Know-How standard the schema describes.
SCHEMA_VERSION = 2


class SchemaError(Exception): ...


@dataclass(frozen=True)
class Spec:
    # For validation purposes only: this code covers a specific iteration of a specific standard,
    # and is designed to reject anything that is not this specific thing.
    name: str  # "Open Know-How"
    okhv: str  # "2.4"
    url: str
    schema_url: str
    publisher: str
    format: str  # "toml"
    filename: str
    encoding: str  # "UTF-8"


class Emit(Enum):
    SCALAR = auto()
    SCALAR_OR_ARRAY = auto()
    TABLE = auto()
    ARRAY_OF_TABLES = auto()


class Obligation(Enum):
    REQUIRED = auto()
    CONDITIONAL = auto()
    RECOMMENDED = auto()
    OPTIONAL = auto()


class Tier(Enum):
    """Mostly a judgment call by this software designer, not part of the standard. If the standard
    *requires* it, though, it's 'core' by definition."""

    GENERATED = auto()
    CORE = auto()
    STANDARD = auto()
    ADVANCED = auto()


class FieldType(Enum):
    TEXT = auto()
    PARAGRAPH = auto()
    NUMBER = auto()
    URL = auto()
    REL_PATH_OR_URL = auto()
    LANGUAGE = auto()
    SPDX_EXPRESSION = auto()
    EMAIL = auto()
    DOI_OR_URL = auto()
    CPC_CLASS = auto()
    ENUM = auto()
    AGENT = auto()
    OBJECT = auto()


class ConditionKind(Enum):
    # As of this writing, these were the only three conditions used in the standard (which is why
    # this list feels sort of strange... it's not based on some deeper ontology, it's purely
    # observational).
    PARENT_PRESENT = auto()
    CONSTRAINT = auto()
    TSDC_CONTAINS = auto()


@dataclass(frozen=True)
class Condition:
    kind: ConditionKind
    argument: str | None


@dataclass(frozen=True)
class Constraint:
    id: str
    type: str
    field: str
    children: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class VocabEntry:
    value: str
    label: str
    help: str | None
    category: str | None


@dataclass(frozen=True)
class VocabCategory:
    id: str
    label: str


@dataclass(frozen=True)
class Vocabulary:
    name: str
    label: str
    open: bool
    custom_pattern: str | None
    help: str | None
    source: str | None
    source_version: str | None
    values: tuple[VocabEntry, ...]
    categories: tuple[VocabCategory, ...]

    def allows(self, value: str) -> bool:
        """Is this value permitted by this vocabulary?"""
        if self.entry(value) is not None:
            return True
        if not self.open:
            return False
        if self.custom_pattern is None:
            return True
        return re.search(self.custom_pattern, value) is not None

    def entry(self, value: str) -> VocabEntry | None:
        """Get the entry for this value, or None if the value does not exist."""
        for entry in self.values:
            if value == entry.value:
                return entry
        return None


@dataclass(frozen=True)
class Field:
    key: str
    path: tuple[str, ...]
    label: str
    help: str | None
    type: FieldType
    obligation: Obligation
    emit: Emit
    tier: Tier | None
    vocabulary: Vocabulary | None
    constraint: Constraint | None
    condition: Condition | None
    children: tuple[Field, ...]
    multiple: bool
    repeatable: bool
    unit: str | None
    minimum_exclusive: float | None
    exactly: int | None
    const: str | None
    default: str | None
    default_from: str | None
    computed_from: str | None
    forms: tuple[str, ...] | None
    canonical_form: str | None

    def walk(self) -> Iterator[Field]:
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    tier: Tier
    help: str
    fields: tuple[Field, ...]


@dataclass(frozen=True)
class Schema:
    spec: Spec
    groups: tuple[Group, ...]
    vocabularies: Mapping[str, Vocabulary]
    constraints: Mapping[str, Constraint]

    def top_level(self) -> Iterator[Field]:
        """Iterate over the top-level fields, but *not* their children"""
        for group in self.groups:
            yield from group.fields

    def walk(self) -> Iterator[Field]:
        """Flatten the structure and yield one field at a time, depth-first"""
        for field in self.top_level():
            yield from field.walk()

    # We can cache because we know the whole structure at load-time
    @cached_property
    def _by_path(self) -> Mapping[tuple[str, ...], Field]:
        return MappingProxyType({field.path: field for field in self.walk()})

    def field(self, *path: str) -> Field:
        """Find a particular field from its component names."""
        try:
            return self._by_path[path]
        except KeyError:
            raise KeyError(".".join(path)) from None


def _read_yaml(schema_path: str | Path | None = None) -> dict[str, Any]:
    yaml_file = Path(schema_path) if schema_path else None
    if yaml_file is None:
        yaml_file = (
            importlib.resources.files("freecad.OpenKnowHowMetadata")
            / "resources"
            / "okh_schema.yaml"
        )

    if yaml_file is None:
        raise FileNotFoundError("Could not find a schema file")

    if not yaml_file.is_file():
        raise FileNotFoundError(f"{yaml_file} is not a file")

    yaml_data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))

    if not isinstance(yaml_data, dict):
        raise SchemaError(f"{yaml_file}: not a YAML mapping")

    version = yaml_data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaError(
            f"{yaml_file}: schema_version is {version!r}, but this code reads {SCHEMA_VERSION}"
        )

    return yaml_data


def _enum(cls, raw: str, error_noun: str, location: str):
    """Coerce a YAML string to an enum member. Values are lower case in the file and the member
    names are the same words upper-case. Works for all the enums in this schema, by construction."""
    try:
        return cls[raw.upper()]
    except (KeyError, AttributeError):
        raise SchemaError(f"{location}: unknown {error_noun} {raw!r}") from None


def _optional_enum(cls, raw: str | None, error_noun: str, location: str, default=None):
    """Same as above but no error if raw is None (gets None in that case)"""
    return default if raw is None else _enum(cls, raw, error_noun, location)


def _require(data: Mapping[str, Any], key: str, location: str):
    """Make sure to transform the KeyError that gets raised into a SchemaError"""
    try:
        return data[key]
    except KeyError:
        raise SchemaError(f"{location}: missing {key!r}") from None


def _lookup(table: Mapping[str, Any], reference: str | None, error_noun: str, location: str):
    """Try to look up a value in a table:"""
    if reference is None:
        return None
    try:
        return table[reference]
    except KeyError:
        raise SchemaError(f"{location}: unknown {error_noun} {reference!r}") from None


def _str_tuple(value, error_noun: str, location: str) -> tuple[str, ...]:
    """Convert a YAML list of strings into a tuple. Guards the case where tuple() would silently
    dismantle a bare string into one character per element, which is basically never intended
    (certainly not in this parser)."""
    if not isinstance(value, list):
        raise SchemaError(f"{location}: {error_noun} must be a list, not {type(value).__name__}")
    if not all(isinstance(item, str) for item in value):
        raise SchemaError(f"{location}: {error_noun} must be a list of strings")
    return tuple(value)


def _build_spec(yaml_data: dict[str, Any]) -> Spec:
    return Spec(
        name=_require(yaml_data, "name", "spec"),
        okhv=_require(yaml_data, "okhv", "spec"),
        url=_require(yaml_data, "url", "spec"),
        schema_url=_require(yaml_data, "schema_url", "spec"),
        publisher=_require(yaml_data, "publisher", "spec"),
        format=_require(yaml_data, "format", "spec"),
        filename=_require(yaml_data, "filename", "spec"),
        encoding=_require(yaml_data, "encoding", "spec"),
    )


def _build_constraint(data: dict) -> Constraint:
    constraint_id = _require(data, "id", "constraint")
    return Constraint(
        id=constraint_id,
        type=_require(data, "type", constraint_id),
        field=_require(data, "field", constraint_id),
        children=_str_tuple(_require(data, "children", constraint_id), "children", constraint_id),
        message=_require(data, "message", constraint_id),
    )


def _build_constraints(data: list[dict[str, Any]]) -> Mapping[str, Constraint]:
    constraints = tuple(_build_constraint(entry) for entry in data)
    if len({constraint.id for constraint in constraints}) != len(constraints):
        raise SchemaError("constraints: duplicate id")
    return MappingProxyType({constraint.id: constraint for constraint in constraints})


def _build_vocabulary_entry(data: dict[str, Any], location: str) -> VocabEntry:
    return VocabEntry(
        label=_require(data, "label", location),
        value=_require(data, "value", location),
        category=data.get("category"),
        help=data.get("help"),
    )


def _build_vocabulary_category(data: dict[str, Any], location: str) -> VocabCategory:
    return VocabCategory(
        id=_require(data, "id", location),
        label=_require(data, "label", location),
    )


def _build_vocabulary(vocabulary_name: str, data: dict) -> Vocabulary:
    values = tuple(
        _build_vocabulary_entry(entry, vocabulary_name)
        for entry in _require(data, "values", vocabulary_name)
    )
    categories = tuple(
        _build_vocabulary_category(entry, vocabulary_name) for entry in data.get("categories", [])
    )
    return Vocabulary(
        name=vocabulary_name,
        label=_require(data, "label", vocabulary_name),
        open=_require(data, "open", vocabulary_name),
        custom_pattern=data.get("custom_pattern"),
        help=data.get("help"),
        source=data.get("source"),
        source_version=data.get("source_version"),
        values=values,
        categories=categories,
    )


def _build_vocabularies(data: dict[str, Any]) -> Mapping[str, Vocabulary]:
    return MappingProxyType(
        {
            vocabulary_name: _build_vocabulary(vocabulary_name, entry)
            for vocabulary_name, entry in data.items()
        }
    )


def _build_condition(raw: str, location: str, refs: _References) -> Condition:
    kind_text, _, argument = raw.partition(":")  # By construction of our YAML
    kind = _enum(ConditionKind, kind_text, "condition", location)
    argument = argument or None
    if kind is ConditionKind.PARENT_PRESENT:
        if argument is not None:
            raise SchemaError(f"{location}: condition {raw!r} takes no argument")
    elif argument is None:
        raise SchemaError(f"{location}: condition {raw!r} needs an argument")
    elif kind is ConditionKind.CONSTRAINT and argument not in refs.constraints:
        raise SchemaError(f"{location}: condition names unknown constraint {argument!r}")
    elif kind is ConditionKind.TSDC_CONTAINS:
        tsdc = _require(refs.vocabularies, "tsdc", location)
        if tsdc.entry(argument) is None:
            raise SchemaError(f"{location}: condition names unknown tsdc code {argument!r}")
    return Condition(kind=kind, argument=argument)


@dataclass(frozen=True)
class _References:
    vocabularies: Mapping[str, Vocabulary]
    constraints: Mapping[str, Constraint]


def _build_field(data: dict, parent_path: tuple[str, ...], refs: _References) -> Field:
    key = _require(data, "key", ".".join(parent_path) or "<root>")
    field_path = parent_path + (key,)
    location = ".".join(field_path)  # for this field's own error messages
    return Field(
        key=key,
        path=field_path,
        label=_require(data, "label", location),
        help=data.get("help"),
        type=_enum(FieldType, _require(data, "type", location), "type", location),
        obligation=_enum(
            Obligation, _require(data, "obligation", location), "obligation", location
        ),
        emit=_optional_enum(Emit, data.get("emit"), "emit", location)
        if data.get("emit")
        else Emit.SCALAR,
        tier=_optional_enum(Tier, data.get("tier"), "tier", location),
        vocabulary=_lookup(refs.vocabularies, data.get("vocabulary"), "vocabulary", location),
        constraint=_lookup(refs.constraints, data.get("constraint"), "constraint", location),
        condition=_build_condition(data.get("condition"), location, refs)
        if data.get("condition")
        else None,
        children=tuple(_build_field(entry, field_path, refs) for entry in data.get("children"))
        if data.get("children")
        else (),
        multiple=data.get("multiple", False),
        repeatable=data.get("repeatable", False),
        unit=data.get("unit"),
        minimum_exclusive=data.get("minimum_exclusive"),
        exactly=data.get("exactly"),
        const=data.get("const"),
        default=data.get("default"),
        default_from=data.get("default_from"),
        computed_from=data.get("computed_from"),
        forms=_str_tuple(data["forms"], "forms", location) if "forms" in data else None,
        canonical_form=data.get("canonical_form"),
    )


def _build_group(data: dict, refs: _References) -> Group:
    group_id = _require(data, "id", "group")
    parent_path = ()
    fields = tuple(
        _build_field(entry, parent_path, refs) for entry in _require(data, "fields", group_id)
    )
    return Group(
        id=group_id,
        label=_require(data, "label", group_id),
        tier=_enum(Tier, _require(data, "tier", group_id), "tier", group_id),
        help=_require(data, "help", group_id),
        fields=fields,
    )


def load(schema_path: str | Path | None = None) -> Schema:
    """Load a schema from a YAML file. If none is passed, load the one from
    resources/okh_schema.yaml (normal calling code uses that mechanism, the argument
    is mostly for testing purposes)."""
    yaml_data = _read_yaml(schema_path)
    spec = _build_spec(_require(yaml_data, "spec", ""))
    constraints = _build_constraints(_require(yaml_data, "constraints", ""))
    vocabularies = _build_vocabularies(_require(yaml_data, "vocabularies", ""))
    # In the file, there is a section of "fragments" here, but their point is to help build the
    # YAML file, we don't need (or want) to load them here. So we just start reading groups now
    refs = _References(vocabularies, constraints)
    groups = tuple(_build_group(entry, refs) for entry in _require(yaml_data, "groups", ""))

    return Schema(spec=spec, groups=groups, vocabularies=vocabularies, constraints=constraints)
