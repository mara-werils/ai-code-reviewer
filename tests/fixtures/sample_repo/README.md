# Sample Project

A sample project for testing the PR Reviewer Agent indexer.

## Installation

```bash
pip install -e .
```

## Usage

```python
from main import create_app

app = create_app()
```

## Architecture

The project follows a simple modular structure:
- `main.py` - Application entry point and configuration
- `utils.js` - Frontend utility functions

### Design Decisions

We chose SQLite for local development and PostgreSQL for production.
Authentication uses JWT tokens with 1-hour expiry.
