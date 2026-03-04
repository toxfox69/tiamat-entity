# TIAMAT Memory API — Documentation

**Base URL:** `https://memory.tiamat.live`
**Version:** 1.0
**Protocol:** HTTPS only
**Content-Type:** `application/json`

Persistent cloud memory for AI agents. Store unstructured text, structured knowledge triples, and recall them via full-text search (FTS5) with word-overlap fallback scoring.

---

## Table of Contents

1. [Authentication](#authentication)
2. [Tiers & Pricing](#tiers--pricing)
3. [Paid Access (x402)](#paid-access-x402)
4. [Endpoints](#endpoints)
   - [GET /health](#get-health)
   - [POST /api/keys/register](#post-apikeysregister)
   - [POST /api/memory/store](#post-apimemorystore)
   - [GET /api/memory/recall](#get-apimemoryrecall)
   - [POST /api/memory/learn](#post-apimemorylearn)
   - [GET /api/memory/list](#get-apimemorylist)
   - [GET /api/memory/stats](#get-apimemorystats)
5. [Error Reference](#error-reference)
6. [Rate Limits](#rate-limits)
7. [OpenAPI 3.0 Specification](#openapi-30-specification)

---

## Authentication

All endpoints except `/health` and `/api/keys/register` require an API key.

Pass your key in **one** of three ways (checked in order):

| Method | Header / Parameter |
|--------|--------------------|
| Bearer token (preferred) | `Authorization: Bearer mem_xxxx` |
| Custom header | `X-API-Key: mem_xxxx` |
| Query param | `?api_key=mem_xxxx` |
| Request body | `{"api_key": "mem_xxxx", ...}` |

API keys have the format `mem_` followed by 43 URL-safe base64 characters (total ~47 chars).

---

## Tiers & Pricing

| Feature | Free Tier | Paid (x402) |
|---------|-----------|-------------|
| Memory storage | 10 memories / key | Unlimited |
| Recalls per day | 50 / key | Unlimited |
| Knowledge triples | Counted against memory limit | Unlimited |
| Cost | $0.00 | $0.01 USDC per 100 additional memories |
| Payment method | — | USDC on Base via x402 |

---

## Paid Access (x402)

To unlock unlimited storage and recalls, include a payment proof header on any request:

```
X-Payment-Proof: <on-chain-tx-hash>
```

Send **$0.05 USDC** (Base mainnet) to the TIAMAT wallet:

```
0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE
```

Then include the transaction hash in `X-Payment-Proof`. The API verifies the payment on-chain before serving the request.

x402 is an HTTP-native micropayment protocol — no accounts, no subscriptions, just cryptographic proof of payment per request.

---

## Endpoints

---

### GET /health

Check service health and current tier limits. No authentication required.

**Request**

```bash
curl https://memory.tiamat.live/health
```

**Response 200**

```json
{
  "status": "healthy",
  "service": "TIAMAT Memory API",
  "version": "1.0",
  "free_tier": {
    "memory_limit": 10,
    "recalls_per_day": 50
  },
  "paid_tier": {
    "price": "$0.01 USDC per 100 additional memories",
    "method": "x402 — include X-Payment-Proof header"
  }
}
```

**Response 500**

```json
{
  "status": "unhealthy",
  "error": "Internal server error"
}
```

---

### POST /api/keys/register

Issue a free API key. No signup, no email required.

**Rate limit:** 5 registrations per IP per hour (1-hour lockout on breach).

**Request**

```bash
curl -X POST https://memory.tiamat.live/api/keys/register \
  -H "Content-Type: application/json" \
  -d '{"label": "my-agent-v1"}'
```

**Request Body (optional)**

| Field | Type | Max | Description |
|-------|------|-----|-------------|
| `label` | string | 100 chars | Human-readable label for this key |

**Response 201**

```json
{
  "api_key": "mem_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfG",
  "tier": "free",
  "limits": {
    "memory_storage": 10,
    "recalls_per_day": 50
  },
  "message": "Save your API key — it will not be shown again.",
  "usage": {
    "store": "curl -X POST https://memory.tiamat.live/api/memory/store -H \"Authorization: Bearer <key>\" -H \"Content-Type: application/json\" -d '{\"content\":\"...\"}'",
    "recall": "curl \"https://memory.tiamat.live/api/memory/recall?api_key=<key>&query=hello&limit=5\""
  }
}
```

> **Important:** The API key is shown only once. Store it securely.

**Response 429**

```json
{
  "error": "Too many registrations. Try again later.",
  "retry_after_seconds": 3456
}
```

---

### POST /api/memory/store

Store a memory (unstructured text with optional metadata).

Free tier: up to **10 memories** per key. Paid tier (x402): unlimited.

**Request**

```bash
curl -X POST https://memory.tiamat.live/api/memory/store \
  -H "Authorization: Bearer mem_xxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "The user prefers dark mode and compact layouts.",
    "tags": ["preference", "ui"],
    "importance": 0.9
  }'
```

**Request Body**

| Field | Type | Required | Default | Constraints | Description |
|-------|------|----------|---------|-------------|-------------|
| `content` | string | Yes | — | Max 10,000 chars | The memory text to store |
| `tags` | array[string] | No | `[]` | Max 20 tags | Searchable labels |
| `importance` | float | No | `0.5` | 0.0 – 1.0 | Priority weight for retrieval ordering |

**Response 201**

```json
{
  "success": true,
  "memory_id": 42,
  "content_length": 46,
  "tags": ["preference", "ui"],
  "importance": 0.9,
  "charged": false,
  "memories_used": 3,
  "memories_limit": 10
}
```

| Field | Type | Description |
|-------|------|-------------|
| `memory_id` | integer | Unique ID for this memory |
| `charged` | boolean | `true` if x402 payment was applied |
| `memories_used` | integer | Total memories stored for this key |
| `memories_limit` | integer \| "unlimited" | Storage cap |

**Paid tier example (x402)**

```bash
curl -X POST https://memory.tiamat.live/api/memory/store \
  -H "Authorization: Bearer mem_xxxx" \
  -H "X-Payment-Proof: 0xabc123...your_tx_hash" \
  -H "Content-Type: application/json" \
  -d '{"content": "Eleventh memory and beyond — unlimited storage."}'
```

---

### GET /api/memory/recall

Full-text search across your stored memories using FTS5 (with word-overlap fallback).

Free tier: **50 recalls per day** per key. Paid tier: unlimited.

**Request**

```bash
curl "https://memory.tiamat.live/api/memory/recall?query=dark+mode&limit=5" \
  -H "Authorization: Bearer mem_xxxx"
```

**Query Parameters**

| Parameter | Type | Required | Default | Constraints | Description |
|-----------|------|----------|---------|-------------|-------------|
| `query` | string | Yes | — | — | Search query text |
| `limit` | integer | No | `5` | 1 – 50 | Max results to return |
| `api_key` | string | No | — | — | API key (if not using header) |

**Response 200**

```json
{
  "query": "dark mode",
  "results": [
    {
      "id": 42,
      "content": "The user prefers dark mode and compact layouts.",
      "tags": ["preference", "ui"],
      "importance": 0.9,
      "created_at": "2026-03-04T12:00:00.000000",
      "access_count": 3
    }
  ],
  "count": 1,
  "recalls_remaining_today": 49,
  "charged": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `results` | array | Matched memories, ordered by FTS5 rank then importance |
| `access_count` | integer | How many times this memory has been recalled |
| `recalls_remaining_today` | integer \| "unlimited" | Remaining daily quota |
| `charged` | boolean | `true` if x402 payment was applied |

**Search algorithm:** FTS5 full-text search is attempted first. If it yields no results, word-overlap scoring is applied across the most recent 500 memories ordered by importance.

---

### POST /api/memory/learn

Store a structured knowledge triple (subject → predicate → object). Triples are stored in a separate knowledge table and count toward the free-tier memory limit.

**Request**

```bash
curl -X POST https://memory.tiamat.live/api/memory/learn \
  -H "Authorization: Bearer mem_xxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Python",
    "predicate": "is",
    "object": "a programming language",
    "confidence": 0.99
  }'
```

**Request Body**

| Field | Type | Required | Default | Constraints | Description |
|-------|------|----------|---------|-------------|-------------|
| `subject` | string | Yes | — | Max 1,000 chars | The entity or concept |
| `predicate` | string | Yes | — | Max 1,000 chars | The relationship type |
| `object` | string | Yes | — | Max 1,000 chars | The target entity or value |
| `confidence` | float | No | `1.0` | 0.0 – 1.0 | Confidence score for this triple |

**Response 201**

```json
{
  "success": true,
  "triple_id": 7,
  "subject": "Python",
  "predicate": "is",
  "object": "a programming language",
  "confidence": 0.99,
  "charged": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Always `true` on successful storage |
| `triple_id` | integer | Unique ID for this triple |
| `charged` | boolean | `true` if x402 payment was applied |

**Use cases:** Build a knowledge graph about entities your agent interacts with — users, tools, preferences, domain facts.

---

### GET /api/memory/list

List your stored memories in reverse importance order, with pagination.

**Request**

```bash
curl "https://memory.tiamat.live/api/memory/list?limit=20&offset=0" \
  -H "Authorization: Bearer mem_xxxx"
```

**Query Parameters**

| Parameter | Type | Required | Default | Constraints | Description |
|-----------|------|----------|---------|-------------|-------------|
| `limit` | integer | No | `20` | 1 – 100 | Number of results per page |
| `offset` | integer | No | `0` | ≥ 0 | Pagination offset |
| `api_key` | string | No | — | — | API key (if not using header) |

**Response 200**

```json
{
  "memories": [
    {
      "id": 42,
      "content": "The user prefers dark mode and compact layouts.",
      "tags": ["preference", "ui"],
      "importance": 0.9,
      "created_at": "2026-03-04T12:00:00.000000",
      "access_count": 3
    },
    {
      "id": 41,
      "content": "Project deadline is March 15th. Budget approved fo…",
      "tags": ["project", "deadline"],
      "importance": 0.7,
      "created_at": "2026-03-03T09:30:00.000000",
      "access_count": 1
    }
  ],
  "total": 8,
  "limit": 20,
  "offset": 0
}
```

> **Note:** `content` is truncated to 200 characters in list responses. Use `recall` to retrieve full content.

---

### GET /api/memory/stats

Usage statistics for your API key.

**Request**

```bash
curl "https://memory.tiamat.live/api/memory/stats" \
  -H "Authorization: Bearer mem_xxxx"
```

**Response 200**

```json
{
  "api_key_hint": "mem_AbCd…",
  "tier": "free",
  "memories": 8,
  "knowledge_triples": 2,
  "total_ops": 34,
  "recalls_today": 12,
  "recalls_limit": 50,
  "memory_limit": 10,
  "created_at": "2026-03-01T08:00:00.000000",
  "last_used": "2026-03-04T12:00:00.000000"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `api_key_hint` | string | First 8 chars + ellipsis (key never returned in full) |
| `tier` | string | `"free"` or `"paid"` |
| `memories` | integer | Unstructured memories stored |
| `knowledge_triples` | integer | Structured triples stored |
| `total_ops` | integer | Lifetime operation count |
| `recalls_today` | integer | Recalls used today (resets at UTC midnight) |
| `memory_limit` | integer \| "unlimited" | Storage cap for your tier |

---

## Error Reference

All error responses return JSON with at minimum an `"error"` field.

| HTTP Status | Error | Cause |
|-------------|-------|-------|
| `400 Bad Request` | `"content" field is required` | Missing required body field |
| `400 Bad Request` | `content too long (max 10 000 chars)` | Payload exceeds limit |
| `400 Bad Request` | `"query" parameter is required` | Missing `query` param on recall |
| `400 Bad Request` | `"subject", "predicate", and "object" are all required` | Incomplete triple |
| `401 Unauthorized` | `API key required` | No key provided |
| `402 Payment Required` | *(x402 payment response)* | Paid tier required; daily quota hit |
| `403 Forbidden` | `Invalid API key` | Key not found or revoked |
| `403 Forbidden` | `quota_exceeded` | Free memory limit reached |
| `429 Too Many Requests` | `Too many registrations. Try again later.` | Key registration rate limit |
| `500 Internal Server Error` | `Internal server error` | Unexpected server failure |

**Quota exceeded response (403)**

```json
{
  "error": "quota_exceeded",
  "limit": 10,
  "current": 10,
  "upgrade_url": "https://tiamat.live/pay"
}
```

**Payment required response (402)**

```json
{
  "error": "Payment required",
  "amount": "0.05 USDC",
  "wallet": "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE",
  "chain": "Base",
  "header": "X-Payment-Proof",
  "instructions": "Send USDC to the wallet above, then include the tx hash in X-Payment-Proof"
}
```

---

## Rate Limits

| Scope | Limit | Window | Lockout |
|-------|-------|--------|---------|
| Key registration | 5 per IP | 1 hour | 1 hour |
| Recall (free tier) | 50 per key | 1 day (UTC) | Upgrade via x402 |
| Memory storage (free tier) | 10 total per key | Lifetime | Upgrade via x402 |
| Max payload | 1 MB | Per request | — |

Recall quotas reset at **UTC midnight**. Storage limits are lifted by including a valid `X-Payment-Proof` header on any request.

---

## OpenAPI 3.0 Specification

```json
{
  "openapi": "3.0.3",
  "info": {
    "title": "TIAMAT Memory API",
    "description": "Persistent cloud memory for AI agents. Store unstructured text and structured knowledge triples. Recall via FTS5 full-text search. Free tier included, paid tier via x402 micropayments.",
    "version": "1.0.0",
    "contact": {
      "name": "TIAMAT / ENERGENAI LLC",
      "url": "https://tiamat.live",
      "email": "tiamat@tiamat.live"
    },
    "license": {
      "name": "Proprietary"
    }
  },
  "servers": [
    {
      "url": "https://memory.tiamat.live",
      "description": "Production"
    }
  ],
  "security": [
    { "BearerAuth": [] }
  ],
  "components": {
    "securitySchemes": {
      "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "description": "API key with `mem_` prefix. Also accepted via X-API-Key header, api_key query param, or api_key body field."
      },
      "ApiKeyHeader": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key"
      },
      "PaymentProof": {
        "type": "apiKey",
        "in": "header",
        "name": "X-Payment-Proof",
        "description": "On-chain transaction hash (Base mainnet USDC) to unlock paid tier for this request."
      }
    },
    "schemas": {
      "Memory": {
        "type": "object",
        "properties": {
          "id": {
            "type": "integer",
            "description": "Unique memory identifier",
            "example": 42
          },
          "content": {
            "type": "string",
            "description": "Memory text content",
            "example": "The user prefers dark mode and compact layouts."
          },
          "tags": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Searchable labels",
            "example": ["preference", "ui"]
          },
          "importance": {
            "type": "number",
            "format": "float",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Priority weight for retrieval ordering",
            "example": 0.9
          },
          "created_at": {
            "type": "string",
            "format": "date-time",
            "description": "UTC ISO 8601 timestamp",
            "example": "2026-03-04T12:00:00.000000"
          },
          "access_count": {
            "type": "integer",
            "description": "Number of times this memory has been recalled",
            "example": 3
          }
        }
      },
      "KnowledgeTriple": {
        "type": "object",
        "properties": {
          "success": {
            "type": "boolean",
            "description": "Always true on successful storage",
            "example": true
          },
          "triple_id": {
            "type": "integer",
            "description": "Unique triple identifier",
            "example": 7
          },
          "subject": {
            "type": "string",
            "description": "The entity or concept",
            "example": "Python"
          },
          "predicate": {
            "type": "string",
            "description": "The relationship type",
            "example": "is"
          },
          "object": {
            "type": "string",
            "description": "The target entity or value",
            "example": "a programming language"
          },
          "confidence": {
            "type": "number",
            "format": "float",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence score for this triple",
            "example": 0.99
          },
          "charged": {
            "type": "boolean",
            "description": "true if x402 payment was applied for this request",
            "example": false
          }
        }
      },
      "ApiKey": {
        "type": "object",
        "properties": {
          "api_key": {
            "type": "string",
            "description": "Full API key — shown only once at registration",
            "example": "mem_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfG"
          },
          "tier": {
            "type": "string",
            "enum": ["free", "paid"],
            "example": "free"
          },
          "limits": {
            "type": "object",
            "properties": {
              "memory_storage": { "type": "integer", "example": 10 },
              "recalls_per_day": { "type": "integer", "example": 50 }
            }
          }
        }
      },
      "ErrorResponse": {
        "type": "object",
        "properties": {
          "error": {
            "type": "string",
            "description": "Machine-readable error code or message",
            "example": "API key required"
          }
        },
        "required": ["error"]
      },
      "QuotaExceededError": {
        "type": "object",
        "properties": {
          "error": { "type": "string", "example": "quota_exceeded" },
          "limit": { "type": "integer", "example": 10 },
          "current": { "type": "integer", "example": 10 },
          "upgrade_url": { "type": "string", "example": "https://tiamat.live/pay" }
        }
      },
      "PaymentRequiredResponse": {
        "type": "object",
        "properties": {
          "error": { "type": "string", "example": "Payment required" },
          "amount": { "type": "string", "example": "0.05 USDC" },
          "wallet": { "type": "string", "example": "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE" },
          "chain": { "type": "string", "example": "Base" },
          "header": { "type": "string", "example": "X-Payment-Proof" },
          "instructions": { "type": "string" }
        }
      }
    }
  },
  "paths": {
    "/health": {
      "get": {
        "summary": "Health check",
        "description": "Returns service health status and current tier configuration. No authentication required.",
        "operationId": "getHealth",
        "security": [],
        "tags": ["System"],
        "responses": {
          "200": {
            "description": "Service is healthy",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "status": { "type": "string", "example": "healthy" },
                    "service": { "type": "string", "example": "TIAMAT Memory API" },
                    "version": { "type": "string", "example": "1.0" },
                    "free_tier": {
                      "type": "object",
                      "properties": {
                        "memory_limit": { "type": "integer", "example": 10 },
                        "recalls_per_day": { "type": "integer", "example": 50 }
                      }
                    },
                    "paid_tier": {
                      "type": "object",
                      "properties": {
                        "price": { "type": "string", "example": "$0.01 USDC per 100 additional memories" },
                        "method": { "type": "string", "example": "x402 — include X-Payment-Proof header" }
                      }
                    }
                  }
                }
              }
            }
          },
          "500": {
            "description": "Service is unhealthy",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/ErrorResponse" }
              }
            }
          }
        }
      }
    },
    "/api/keys/register": {
      "post": {
        "summary": "Register API key",
        "description": "Issue a free API key instantly. No signup required. Rate limited to 5 registrations per IP per hour.",
        "operationId": "registerKey",
        "security": [],
        "tags": ["Keys"],
        "requestBody": {
          "required": false,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "label": {
                    "type": "string",
                    "maxLength": 100,
                    "description": "Optional human-readable label",
                    "example": "my-agent-v1"
                  }
                }
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "API key created",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/ApiKey" }
              }
            }
          },
          "429": {
            "description": "Rate limit exceeded",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "error": { "type": "string" },
                    "retry_after_seconds": { "type": "integer", "example": 3456 }
                  }
                }
              }
            }
          },
          "500": {
            "description": "Internal server error",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/ErrorResponse" }
              }
            }
          }
        }
      }
    },
    "/api/memory/store": {
      "post": {
        "summary": "Store a memory",
        "description": "Store unstructured text with optional tags and importance score. Free tier: 10 memories per key. Paid tier (x402): unlimited.",
        "operationId": "storeMemory",
        "tags": ["Memory"],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["content"],
                "properties": {
                  "content": {
                    "type": "string",
                    "maxLength": 10000,
                    "description": "The memory text to store",
                    "example": "The user prefers dark mode and compact layouts."
                  },
                  "tags": {
                    "type": "array",
                    "items": { "type": "string" },
                    "maxItems": 20,
                    "description": "Searchable labels",
                    "example": ["preference", "ui"]
                  },
                  "importance": {
                    "type": "number",
                    "format": "float",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.5,
                    "description": "Priority weight (higher = retrieved first)",
                    "example": 0.9
                  }
                }
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Memory stored",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "success": { "type": "boolean", "example": true },
                    "memory_id": { "type": "integer", "example": 42 },
                    "content_length": { "type": "integer", "example": 46 },
                    "tags": { "type": "array", "items": { "type": "string" } },
                    "importance": { "type": "number", "example": 0.9 },
                    "charged": { "type": "boolean", "example": false },
                    "memories_used": { "type": "integer", "example": 3 },
                    "memories_limit": { "oneOf": [{ "type": "integer" }, { "type": "string" }], "example": 10 }
                  }
                }
              }
            }
          },
          "400": { "description": "Bad request", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "401": { "description": "API key required", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "402": { "description": "Payment required (quota hit or invalid proof)", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/PaymentRequiredResponse" } } } },
          "403": {
            "description": "Invalid key or quota exceeded",
            "content": {
              "application/json": {
                "schema": {
                  "oneOf": [
                    { "$ref": "#/components/schemas/ErrorResponse" },
                    { "$ref": "#/components/schemas/QuotaExceededError" }
                  ]
                }
              }
            }
          },
          "500": { "description": "Internal server error", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } }
        }
      }
    },
    "/api/memory/recall": {
      "get": {
        "summary": "Search memories",
        "description": "Full-text search (FTS5) across your stored memories with word-overlap fallback. Free tier: 50 recalls per day. Paid tier: unlimited.",
        "operationId": "recallMemory",
        "tags": ["Memory"],
        "parameters": [
          {
            "name": "query",
            "in": "query",
            "required": true,
            "description": "Search query text",
            "schema": { "type": "string", "example": "dark mode" }
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "description": "Maximum results to return",
            "schema": { "type": "integer", "minimum": 1, "maximum": 50, "default": 5 }
          },
          {
            "name": "api_key",
            "in": "query",
            "required": false,
            "description": "API key (alternative to Authorization header)",
            "schema": { "type": "string" }
          }
        ],
        "responses": {
          "200": {
            "description": "Search results",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "query": { "type": "string", "example": "dark mode" },
                    "results": { "type": "array", "items": { "$ref": "#/components/schemas/Memory" } },
                    "count": { "type": "integer", "example": 1 },
                    "recalls_remaining_today": { "oneOf": [{ "type": "integer" }, { "type": "string" }], "example": 49 },
                    "charged": { "type": "boolean", "example": false }
                  }
                }
              }
            }
          },
          "400": { "description": "Missing query parameter", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "401": { "description": "API key required", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "402": { "description": "Payment required (daily quota hit)", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/PaymentRequiredResponse" } } } },
          "403": { "description": "Invalid API key", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "500": { "description": "Internal server error", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } }
        }
      }
    },
    "/api/memory/learn": {
      "post": {
        "summary": "Store a knowledge triple",
        "description": "Store a structured subject→predicate→object triple with an optional confidence score. Triples count toward the free-tier memory limit.",
        "operationId": "learnTriple",
        "tags": ["Knowledge"],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["subject", "predicate", "object"],
                "properties": {
                  "subject": {
                    "type": "string",
                    "maxLength": 1000,
                    "description": "The entity or concept",
                    "example": "Python"
                  },
                  "predicate": {
                    "type": "string",
                    "maxLength": 1000,
                    "description": "The relationship type",
                    "example": "is"
                  },
                  "object": {
                    "type": "string",
                    "maxLength": 1000,
                    "description": "The target entity or value",
                    "example": "a programming language"
                  },
                  "confidence": {
                    "type": "number",
                    "format": "float",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 1.0,
                    "description": "Confidence score for this triple",
                    "example": 0.99
                  }
                }
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Triple stored",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/KnowledgeTriple" }
              }
            }
          },
          "400": { "description": "Missing required fields", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "401": { "description": "API key required", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "402": { "description": "Payment required or quota exceeded", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/PaymentRequiredResponse" } } } },
          "403": { "description": "Invalid API key", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "500": { "description": "Internal server error", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } }
        }
      }
    },
    "/api/memory/list": {
      "get": {
        "summary": "List memories",
        "description": "List all stored memories for your API key, sorted by importance then creation time. Paginated.",
        "operationId": "listMemories",
        "tags": ["Memory"],
        "parameters": [
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "description": "Results per page",
            "schema": { "type": "integer", "minimum": 1, "maximum": 100, "default": 20 }
          },
          {
            "name": "offset",
            "in": "query",
            "required": false,
            "description": "Pagination offset",
            "schema": { "type": "integer", "minimum": 0, "default": 0 }
          },
          {
            "name": "api_key",
            "in": "query",
            "required": false,
            "description": "API key (alternative to Authorization header)",
            "schema": { "type": "string" }
          }
        ],
        "responses": {
          "200": {
            "description": "Paginated memory list",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "memories": { "type": "array", "items": { "$ref": "#/components/schemas/Memory" } },
                    "total": { "type": "integer", "description": "Total memories stored", "example": 8 },
                    "limit": { "type": "integer", "example": 20 },
                    "offset": { "type": "integer", "example": 0 }
                  }
                }
              }
            }
          },
          "401": { "description": "API key required", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "403": { "description": "Invalid API key", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "500": { "description": "Internal server error", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } }
        }
      }
    },
    "/api/memory/stats": {
      "get": {
        "summary": "Usage statistics",
        "description": "Returns lifetime usage statistics for your API key including memory counts, recall quota consumption, and account metadata.",
        "operationId": "memoryStats",
        "tags": ["Keys"],
        "parameters": [
          {
            "name": "api_key",
            "in": "query",
            "required": false,
            "description": "API key (alternative to Authorization header)",
            "schema": { "type": "string" }
          }
        ],
        "responses": {
          "200": {
            "description": "Usage statistics",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "api_key_hint": { "type": "string", "example": "mem_AbCd…" },
                    "tier": { "type": "string", "enum": ["free", "paid"], "example": "free" },
                    "memories": { "type": "integer", "example": 8 },
                    "knowledge_triples": { "type": "integer", "example": 2 },
                    "total_ops": { "type": "integer", "example": 34 },
                    "recalls_today": { "type": "integer", "example": 12 },
                    "recalls_limit": { "type": "integer", "example": 50 },
                    "memory_limit": { "oneOf": [{ "type": "integer" }, { "type": "string" }], "example": 10 },
                    "created_at": { "type": "string", "format": "date-time" },
                    "last_used": { "type": "string", "format": "date-time" }
                  }
                }
              }
            }
          },
          "401": { "description": "API key required", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "403": { "description": "Invalid API key", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } },
          "500": { "description": "Internal server error", "content": { "application/json": { "schema": { "$ref": "#/components/schemas/ErrorResponse" } } } }
        }
      }
    }
  },
  "tags": [
    { "name": "System", "description": "Health and status endpoints" },
    { "name": "Keys", "description": "API key management and usage statistics" },
    { "name": "Memory", "description": "Unstructured memory storage and retrieval" },
    { "name": "Knowledge", "description": "Structured knowledge triple storage" }
  ]
}
```

---

*Generated 2026-03-04 · ENERGENAI LLC · [tiamat.live](https://tiamat.live)*
