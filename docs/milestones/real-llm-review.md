# Real-LLM Review — Gateway + credentials UI

**Date**: 2026-09-07  
**Branch**: `cursor/real-llm-gateway-4365`  
**Base**: `cursor/m4-enterprise-4365`

## Delivered

| Item | Status |
|------|--------|
| OpenAI-compatible + Ollama + local providers | Done |
| Ask routes via gateway; no key → local fallback | Done |
| Learn tries JSON LLM then extractive fallback | Done |
| Tenant `llm_credentials` (sealed key, prefix only) | Done |
| `GET/PUT /v1/admin/llm/credentials`, `/env`, `/ping` | Done |
| Governance UI: **模型与密钥（API Key）** | Done |
| Env: `LLM_API_KEY` / `LLM_BASE_URL` / `OLLAMA_*` | Done |
| Default routes L1/L2 → openai_compatible, L3/L4 → ollama | Done |

## Configure Key (UI)

1. Open http://127.0.0.1:3000/app/governance  
2. Section **模型与密钥（API Key）**  
3. Fill Base URL + model + API Key → Save → Test connection  

Or `.env`:

```bash
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat
```

## Regression

```bash
ruff check packages apps tests
PYTHONPATH=packages:apps python3 -m pytest -q   # 35 passed
cd apps/web && npm run build
```

## Deferred

- Fernet/KMS production sealing  
- Streaming SSE Ask  
- Real embedding models / Qdrant  
- Agent tools full LLM rewrite
