import os
import sys

sys.path.insert(0, os.path.abspath("../src"))

project = "pydsvdcapi"
copyright = "2024, KarlKiel"
author = "KarlKiel"
release = "0.8.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
]

html_theme = "furo"
