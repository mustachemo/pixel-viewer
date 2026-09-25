# Pixel Viewer

A fast, native image viewer that shows the value of every pixel as you zoom in.

## Development

```bash
uv sync                                  # create .venv with runtime and dev dependencies
uv run pytest --cov=pixel_viewer         # tests (rendered off-screen, no display needed)
uvx ruff check src tests && uvx ruff format src tests
```

## License

[MIT](LICENSE) © 2026 Mohamed Hasan
