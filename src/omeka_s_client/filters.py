"""Build filters for Omeka property searches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class PropertyCondition:
    """Describe one property search condition.

    >>> PropertyCondition(10, "ex").property
    10
    """

    property: str | int
    type: str
    value: str | int | None = None
    joiner: Literal["and", "or"] | None = None


def property_filter(
    property: str | int,
    type: str,
    value: str | int | None = None,
    *,
    joiner: Literal["and", "or"] | None = None,
) -> PropertyCondition:
    """Make a condition for a term or numeric ID.

    >>> property_filter("dcterms:identifier", "eq", "abc").value
    'abc'
    """
    return PropertyCondition(property, type, value, joiner)


def property_filters(*conditions: PropertyCondition) -> list[tuple[str, str]]:
    """Number conditions and return query pairs.

    >>> property_filters(property_filter(10, "ex"))
    [('property[0][property]', '10'), ('property[0][type]', 'ex')]
    """
    pairs = []
    for index, condition in enumerate(conditions):
        prefix = f"property[{index}]"
        pairs.extend(
            [(f"{prefix}[property]", str(condition.property)), (f"{prefix}[type]", condition.type)]
        )
        if condition.type not in {"ex", "nex"} and condition.value is not None:
            pairs.append((f"{prefix}[text]", str(condition.value)))
        if condition.joiner is not None:
            pairs.append((f"{prefix}[joiner]", condition.joiner))
    return pairs
