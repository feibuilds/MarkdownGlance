from ..assets.math import math_image_url
from ..assets.mermaid import mermaid_image_url
from ..domain.contracts import DiagnosticStage, PreviewDocument, RenderRequest
from ..renderer import parse, serialise
from .errors import RenderFailure
from .ports import AssetResolverPort


def render(request: RenderRequest, resolver: AssetResolverPort) -> PreviewDocument:
    """Parse, resolve the assets, serialise -- naming the stage that fails.

    Each stage's exception becomes a `RenderFailure` carrying that stage and
    the exception itself. Before this, every failure was reported as the last
    stage, "Serialise", which is where a library that fails to import, a parse
    error and a genuine serialiser bug all ended up (issue #5).
    """
    try:
        parsed = parse(
            request,
            mermaid_url_builder=mermaid_image_url,
            math_url_builder=math_image_url,
        )
    except RenderFailure:
        raise
    except Exception as error:
        raise RenderFailure.wrap(DiagnosticStage.PARSE, error)
    try:
        results = resolver.resolve(parsed.asset_keys, request.session_id)
    except Exception as error:
        raise RenderFailure.wrap(DiagnosticStage.ASSET, error)
    try:
        return serialise(parsed, results, request)
    except Exception as error:
        raise RenderFailure.wrap(DiagnosticStage.SERIALISE, error)
