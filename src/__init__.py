"""MHYVD (Mihoyo Videos Downloader) re-implementation package.

Source layout under ``new/src`` adopting the ``exp/`` conventions: every
module begins with ``from __future__ import annotations``, models are frozen
dataclasses, functionality is split into small single-responsibility modules,
and packages expose metadata through their ``__init__`` files.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
