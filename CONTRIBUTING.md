# Contributing

Use a supported Python version and install [uv](https://docs.astral.sh/uv/). Read the [code of conduct](CODE_OF_CONDUCT.md).

1. Run `uv sync --locked`.
2. Run `uv run --locked prek install --hook-type pre-commit --hook-type commit-msg`.
3. Run `uv run --locked prek run --all-files` before you open a pull request.

Use Conventional Commits for commit messages. Run `uv run --locked git-cliff --offline --output CHANGELOG.md` to update the change log.

Use synthetic records in offline tests. To run integration tests, start Docker and run the following command.

```sh
OMEKA_VERSION=3.2.3 uv run --locked python tests/integration/run.py
```

The script creates a disposable Omeka S installation and removes it at the end. Use `OMEKA_VERSION=4.1.1` or `OMEKA_VERSION=4.2.1` to test the other versions.
