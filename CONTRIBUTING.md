# Contributing to import-analyzer-py

Thank you for your interest in contributing!

## Development Setup

### Prerequisites

- Python 3.10+
- [pre-commit](https://pre-commit.com/)

### Getting Started

```bash
# Clone the repository
git clone https://github.com/cmyui/import-analyzer-py.git
cd import-analyzer-py

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install in development mode with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/detection_test.py -v

# Run a specific test by name
pytest tests/ -v -k "shadowed by variable"

# Run tests with coverage
tox -e py

# Run tests across all Python versions (3.10-3.14)
tox
```

## Code Style

This project uses:
- **isort** for import sorting
- **autopep8** for formatting
- **flake8** for linting
- **mypy** for type checking
- **import-analyzer-py** for import management

All of these run automatically via pre-commit:

```bash
pre-commit run --all-files
```

## Test Organization

Tests follow [pyupgrade](https://github.com/asottile/pyupgrade) patterns:
- One file per feature area
- Heavy use of `pytest.param()` with descriptive IDs
- `_noop` suffix for "should NOT flag" tests
- Flat function style (no test classes)

## Pull Request Guidelines

1. Fork the repository and create a branch from `main`
2. Add tests for any new functionality
3. Ensure all tests pass and pre-commit hooks succeed
4. Update documentation if needed
5. Submit a pull request

## Architecture Overview

See `CLAUDE.md` for detailed architecture documentation, including:
- Package structure
- Core components and their responsibilities
- Key algorithms (cascade detection, LEGB scope analysis)
