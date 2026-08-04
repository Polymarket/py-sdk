# API Reference Artifact

This directory contains the Sphinx source used to generate the Python SDK API
reference artifact consumed by Mintlify.

Run `make api-reference` to create
`build/api-reference/polymarket-client-sphinx.zip`. Sphinx imports the installed
`polymarket-client` package and renders the selected public classes, methods,
models, types, and values from their signatures and docstrings. Warnings fail
the build.

The `API Reference` GitHub Actions workflow can be dispatched manually. It
uploads an artifact identified by the commit SHA for review without publishing
a package or creating a release.

After a successful PyPI publication, the release workflow uploads an immutable
artifact named `polymarket-client-<version>-sphinx.zip` to the corresponding
GitHub Release. That release asset is the stable HTTPS source Mintlify can use:

```json
{
  "tab": "Python Reference",
  "sdk": {
    "format": "sphinx",
    "source": "<versioned GitHub Release asset URL>",
    "directory": "sdk/python"
  }
}
```

The current reference set is intentionally representative for the proof of
concept. Expanding it to the complete supported public surface requires an
explicit module inventory and a coverage check against the built wheel.
