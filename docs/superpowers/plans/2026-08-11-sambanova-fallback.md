# SambaNova Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SambaNova as the final fallback provider for the real-estate assistant chat.

**Architecture:** Load `SAMBANOVA_API_KEY` through `config.py` and append a SambaNova provider entry after Mistral in `tools/db_chat.py`. Reuse the current provider-chain and retryable-error logic.

**Tech Stack:** Python 3.11+, OpenAI-compatible client, pytest, dotenv.

## Global Constraints

- Preserve the existing order and append SambaNova after Mistral.
- Use endpoint `https://api.sambanova.ai/v1` and model `gpt-oss-120b`.
- Never commit or print the real API key.
- Do not change `agent.py` or the independent Gemini agent.

---

### Task 1: Extend the provider-chain regression test

**Files:**
- Modify: `tests/test_db_chat.py`

- [x] **Step 1: Update the expected provider order**

Extend `TestMistralFallback.test_mistral_is_last_after_groq_accounts_and_gemini` so the expected names end with `"mistral", "sambanova"`.

- [x] **Step 2: Run the test to verify it fails**

```powershell
python -X utf8 -m pytest tests/test_db_chat.py -k mistral -q
```

Expected: FAIL because SambaNova is not yet in `_PROVIDER_LIST`.

### Task 2: Wire SambaNova configuration and fallback

**Files:**
- Modify: `config.py`
- Modify: `tools/db_chat.py`
- Modify: `.env.example`

- [x] **Step 1: Add `SAMBANOVA_API_KEY`**

Define `SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "")` beside the other provider keys and document an empty `SAMBANOVA_API_KEY=` entry in `.env.example`.

- [x] **Step 2: Add the provider entry**

Import `SAMBANOVA_API_KEY` in `tools/db_chat.py` and append this entry after Mistral:

```python
{"name": "sambanova", "base_url": "https://api.sambanova.ai/v1",
 "api_key": SAMBANOVA_API_KEY, "model": "gpt-oss-120b"},
```

Add `SAMBANOVA_API_KEY` to both missing-key error messages.

- [x] **Step 3: Run the regression test**

```powershell
python -X utf8 -m pytest tests/test_db_chat.py -k mistral -q
```

Expected: PASS.

### Task 3: Verify and commit

**Files:**
- No additional files.

- [x] **Step 1: Run focused tests and compile**

```powershell
python -X utf8 -m pytest tests/test_db_chat.py -q
python -X utf8 -m py_compile config.py tools/db_chat.py
```

- [x] **Step 2: Check the diff**

```powershell
git diff --check
git diff -- config.py tools/db_chat.py .env.example tests/test_db_chat.py
```

- [x] **Step 3: Commit the implementation**

```powershell
git add config.py tools/db_chat.py .env.example tests/test_db_chat.py docs/superpowers/plans/2026-08-11-sambanova-fallback.md
git commit -m "feat: add SambaNova chat fallback"
```
