from importlib.metadata import version as package_version

from sphinx.application import Sphinx

project = "Polymarket Python SDK"
author = "Polymarket Engineering"
release = package_version("polymarket-client")
version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

autodoc_member_order = "bysource"
autodoc_preserve_defaults = True
autodoc_typehints = "signature"
autodoc_typehints_format = "short"

napoleon_google_docstring = True
napoleon_numpy_docstring = False

add_module_names = False
exclude_patterns = ["_build"]
html_theme = "alabaster"

_CLIENT_CLASSES = {
    "polymarket.AsyncPublicClient",
    "polymarket.AsyncSecureClient",
    "polymarket.PublicClient",
    "polymarket.SecureClient",
}


def _hide_client_constructor(
    _app: Sphinx,
    what: str,
    name: str,
    _obj: object,
    _options: object,
    _signature: str | None,
    return_annotation: str | None,
) -> tuple[str, str | None] | None:
    if what == "class" and name in _CLIENT_CLASSES:
        return "", return_annotation
    return None


def setup(app: Sphinx) -> None:
    app.connect("autodoc-process-signature", _hide_client_constructor)
