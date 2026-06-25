# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
import os
import sys

sys.path.insert(0, os.path.abspath("../src"))

from pydsvdcapi import __version__

project = "pydsvdcapi"
copyright = "2024–2026 Arne Speck"
author = "Arne Speck"
release = __version__

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "tasklist",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "myst",
}

html_theme = "furo"

autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
