"""json-diff-studio — структурное сравнение JSON и JSON Patch (RFC 6902)."""
__version__ = "1.0.0"

from .diff import ArrayKey, Change, Options, diff, summarize  # noqa: E402
from .patch import PatchError, apply_patch, make_patch  # noqa: E402

__all__ = ["ArrayKey", "Change", "Options", "PatchError", "apply_patch",
           "diff", "make_patch", "summarize", "__version__"]
