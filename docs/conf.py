import os
import sys

sys.path.insert(0, os.path.abspath("../src"))

from pydsvdcapi import __version__

project = "pydsvdcapi"
copyright = "2026, KarlKiel"
author = "KarlKiel"
release = __version__

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
]

html_theme = "furo"
