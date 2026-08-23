# tiktoken offline cache

Bundled BPE ranks for `cl100k_base` so pytest does not download from
`openaipublic.blob.core.windows.net` (often blocked or slow in CI).

## File naming

tiktoken caches by **`sha1(blob_url)`**, not by the content `expected_hash`.

- URL: `https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken`
- Cache filename: `9b5ad71b2ce5302211f9c61530b329a4922fc6a4`
- Content SHA-256 (`expected_hash`): `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`

`tests/conftest.py` sets `TIKTOKEN_CACHE_DIR` to this directory (via `setdefault`).

## Regenerate

```bash
# Allow one download into a temp dir, then copy the sha1(url) file here.
TIKTOKEN_CACHE_DIR=/tmp/tiktoken-regen uv run python -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")'
cp /tmp/tiktoken-regen/9b5ad71b2ce5302211f9c61530b329a4922fc6a4 tests/fixtures/tiktoken_cache/
```

Source: OpenAI public encodings (used by the `tiktoken` package; MIT). Test-only fixture.
