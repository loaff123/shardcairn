"""ShardCairn: explicit setup-aware offline planning and independent checking.

Public imports are lazy and do not inspect files, environment, or executors.
"""
from .version import __version__

__all__ = ['__version__','Setup','Unit','Manifest','PlanOptions','VerifyOptions',
           'PlanDocument','VerificationResult','ArtifactResult','load_manifest',
           'canonical_manifest_bytes','plan','verify','export','ShardCairnError']


def __getattr__(name):
    if name in {'Setup','Unit','Manifest','PlanOptions','VerifyOptions','PlanDocument',
                'VerificationResult','ArtifactResult','load_manifest'}:
        from . import manifest
        return getattr(manifest, name)
    if name == 'canonical_manifest_bytes':
        from .canonical import canonical_manifest_bytes
        return canonical_manifest_bytes
    if name == 'plan':
        from .planner import plan
        return plan
    if name == 'verify':
        from .verifier import verify
        return verify
    if name == 'export':
        from .exporter import export
        return export
    if name == 'ShardCairnError':
        from .errors import ShardCairnError
        return ShardCairnError
    raise AttributeError(name)
