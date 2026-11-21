# Contributing

Use a supported Python version and install [uv](https://docs.astral.sh/uv/). Read the [code of conduct](CODE_OF_CONDUCT.md).

## Open a pull request

1. If you lack push access, fork the repository on GitHub.
2. Clone the repository that you can push to.
3. If you cloned a fork, add the original repository as the `upstream` remote.
4. Fetch `main` from the original repository.
5. Create a `work/<task>` branch from the fetched `main` branch.
6. Run `uv sync --locked`.
7. Run `uv run --locked prek install --hook-type pre-commit --hook-type commit-msg`.
8. Run `uv run --locked prek run --all-files` before you commit.
9. Push the feature branch to your fork or the upstream repository.
10. Open a pull request against upstream `main`.

Use Conventional Commits for commit messages and the pull request title. Include one logical change in each pull request. Link the issue that the change addresses.

Before a squash merge, get one approval from another contributor with write access. Resolve all review conversations. Update your branch if it falls behind `main`. The quality gate, CodeQL, and dependency review must pass.

## Run the checks

Run `uv run --locked git-cliff --offline --output CHANGELOG.md` to update the change log.

Use synthetic records in offline tests. To run integration tests, start Docker and run the following command.

```sh
OMEKA_VERSION=3.2.3 uv run --locked python tests/integration/run.py
```

The script creates a disposable Omeka S installation and removes it at the end. Use `OMEKA_VERSION=4.1.1` or `OMEKA_VERSION=4.2.1` to test the other versions.
