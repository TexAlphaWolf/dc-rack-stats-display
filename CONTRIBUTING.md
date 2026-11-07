# Contributing

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy
pytest -m "not browser" --cov
```
Keep the runtime dependency-free (standard library only). New data readers need a test against a fake server,
and anything shown on the page must go in as text, never as HTML.
