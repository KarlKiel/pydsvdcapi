# Contributing

Thank you for your interest in contributing to **pydsvdcapi**!

## Development setup

1. **Clone the repository and create a virtual environment:**

   ```bash
   git clone https://github.com/KarlKiel/pyDSvDCAPI.git
   cd pyDSvDCAPI
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```

2. **Install the package in editable mode with development extras:**

   ```bash
   pip install -e ".[dev]"
   ```

## Project layout

```
src/
└── pydsvdcapi/      # library source (src layout)
    ├── __init__.py  # public API re-exports
    ├── vdc_host.py
    ├── vdc.py
    ├── vdsd.py
    └── ...
tests/               # pytest tests (mirror the src/ structure)
docs/                # documentation (guide.md + Sphinx config)
```

## Running tests

```bash
python -m pytest
```

Run with coverage:

```bash
python -m pytest --cov=pydsvdcapi --cov-report=term-missing
```

## Linting and formatting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
ruff check src/ tests/
ruff format --check src/ tests/
```

Apply fixes automatically:

```bash
ruff check --fix src/ tests/
ruff format src/ tests/
```

## Type checking

```bash
mypy src/pydsvdcapi
```

## Commit guidelines

- Use the present tense ("Add feature" not "Added feature").
- Reference issue numbers where applicable (`Fixes #42`).
- Keep commits focused; one logical change per commit.

## Changelog

Update [CHANGELOG.md](CHANGELOG.md) under the `[Unreleased]` section when
adding user-visible changes. Follow the [Keep a Changelog](https://keepachangelog.com/)
format.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Make your changes with tests.
3. Ensure `pytest`, `ruff check`, and `mypy` all pass.
4. Open a pull request against `main`.
