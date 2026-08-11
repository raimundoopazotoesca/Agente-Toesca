# Mistral Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Mistral as the final fallback provider for the real-estate assistant chat.

**Architecture:** Load `MISTRAL_API_KEY` through the existing configuration module and append a Mistral provider entry to `tools/db_chat.py` after Gemini. Reuse the current provider-chain and retryable-error logic so Mistral is attempted only after configured earlier providers fail due to quota/rate-limit errors.

**Tech Stack:** Python 3.11+, OpenAI-compatible Python client, pytest, dotenv.

## Global Constraints

- Preserve the existing provider order: Groq 1 → Groq 2 → Groq 3 → Gemini → Mistral when `DB_CHAT_PROVIDER=groq`.
- Use `MISTRAL_API_KEY`; never commit or print the real secret.
- Use Mistral endpoint `https://api.mistral.ai/v1` and model `mistral-large-latest`.
- Do not change `agent.py` or the independent Gemini agent.

---

### Task 1: Add the provider-chain regression test

**Files:**
- Modify: `tests/test_db_chat.py`

**Interfaces:**
- Consumes: `tools.db_chat._provider_chain` and its module-level provider configuration.
- Produces: A deterministic regression test proving Mistral is ordered after Gemini.

- [x] **Step 1: Write the failing test**

Add a test that temporarily replaces `_PROVIDER_LIST` with configured Groq, Gemini, and Mistral entries, sets `DB_CHAT_PROVIDER` to `groq`, calls `_provider_chain()`, and asserts provider names are `['groq', 'groq', 'groq', 'gemini', 'mistral']`.

- [x] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -X utf8 -m pytest tests/test_db_chat.py -k mistral -q
```

Expected: FAIL because the current provider list has no Mistral entry.

### Task 2: Wire Mistral configuration and fallback

**Files:**
- Modify: `config.py`
- Modify: `tools/db_chat.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `MISTRAL_API_KEY` from the process environment.
- Produces: A provider config with `name='mistral'`, `base_url='https://api.mistral.ai/v1'`, and `model='mistral-large-latest'`.

- [x] **Step 1: Add the configuration variable**

In `config.py`, define `MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY', '')` beside the other provider keys. Document the variable in `.env.example` without a real value.

- [x] **Step 2: Add Mistral to `tools/db_chat.py`**

Import `MISTRAL_API_KEY`, append the Mistral provider after Gemini in `_PROVIDER_LIST`, and include `MISTRAL_API_KEY` in the missing-key error messages.

- [x] **Step 3: Run the regression test**

Run:

```powershell
python -X utf8 -m pytest tests/test_db_chat.py -k mistral -q
```

Expected: PASS.

### Task 3: Verify the complete change

**Files:**
- No additional files.

- [x] **Step 1: Run focused tests**

```powershell
python -X utf8 -m pytest tests/test_db_chat.py -q
```

- [x] **Step 2: Compile modified Python modules**

```powershell
python -X utf8 -m py_compile config.py tools/db_chat.py
```

- [x] **Step 3: Inspect the diff and confirm no secrets are present**

```powershell
git diff --check
git diff -- config.py tools/db_chat.py .env.example tests/test_db_chat.py
```

- [x] **Step 4: Commit the implementation**

```powershell
git add config.py tools/db_chat.py .env.example tests/test_db_chat.py
git commit -m "feat: add Mistral chat fallback"
```
