from ..assets.math import math_image_url
from ..assets.mermaid import mermaid_image_url
from ..domain.contracts import PreviewDocument, RenderRequest
from ..renderer import parse, serialise
from .ports import AssetResolverPort


def render(request: RenderRequest, resolver: AssetResolverPort) -> PreviewDocument:
    parsed = parse(
        request,
        mermaid_url_builder=mermaid_image_url,
        math_url_builder=math_image_url,
    )
    results = resolver.resolve(parsed.asset_keys, request.session_id)
    return serialise(parsed, results, request)
