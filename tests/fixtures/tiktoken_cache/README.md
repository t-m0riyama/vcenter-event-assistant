# tiktoken offline cache

`cl100k_base` BPE ranks for `tiktoken` (hash filename matches
`tiktoken_ext.openai_public.cl100k_base` `expected_hash`).

`tests/conftest.py` sets `TIKTOKEN_CACHE_DIR` here so pytest does not download
from `openaipublic.blob.core.windows.net` (often blocked or slow in CI).
