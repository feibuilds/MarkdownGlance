from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from ..domain.contracts import AssetKey, Heading


@dataclass
class TextNode:
    text: str


@dataclass
class ElementNode:
    tag: str
    attrs: Dict[str, str] = field(default_factory=dict)
    children: List["Node"] = field(default_factory=list)
    asset_key: Optional[AssetKey] = None
    generated: bool = False


Node = Union[TextNode, ElementNode]


@dataclass(frozen=True)
class StructuredDoc:
    roots: Tuple[Node, ...]
    headings: Tuple[Heading, ...]
    asset_keys: Tuple[AssetKey, ...]
    links: Tuple[str, ...]
    # Fenced code coloured in the theme it was parsed under.
    highlighted: bool = False
