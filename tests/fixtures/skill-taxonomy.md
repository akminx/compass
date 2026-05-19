---
type: taxonomy
canonical: true
last_updated: 2026-05-17
---

# Skill Taxonomy

The canonical list of skills Compass tracks. Every JD-extracted skill is normalized against this list before scoring or aggregation. Synonyms route to the canonical name.

Categories follow the JD-market keyword stack (job-market report Section 2). Add a skill only when at least one JD in the wild has used the term and it's distinct enough to track separately.

## Rubric (used by skill_assessor)

| Level | Definition | Evidence required |
|---|---|---|
| 0 | No exposure | none |
| 1 | Tutorial-level | course notes, "hello world", or a read paper |
| 2 | Applied in personal project | repo or vault note showing real use, but no users beyond self |
| 3 | Shipped | deployed, evals exist, OR used by people other than you |
| 4 | Production-grade | shipped + observability + cost tracking + recovered from a real failure |
| 5 | Authority | taught it, merged upstream PR, fixed a non-trivial bug in the library |

Asymmetric promotion: jumping 2+ levels in one assessment requires HiTL approval.

---

## Languages

| Canonical | Synonyms | Tier-2 demand | Tier-3 demand |
|---|---|---|---|
| Python | python3, py | high | high |
| TypeScript | ts, typescript | high | medium |
| JavaScript | js, javascript, node, nodejs | medium | medium |
| Go | golang | medium | low |
| SQL | postgres-sql, mysql, ansi-sql | medium | high |

## LLM APIs & SDKs

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| LLMs | large language models, large language model, language models, language model, llm, llms, generative ai, gen ai, genai | high | high |
| Machine Learning | ml, machine-learning, applied ml, applied machine learning | medium | high |
| Deep Learning | dl, deep-learning, neural networks, neural-networks | low | medium |
| Reinforcement Learning | rl, reinforcement-learning, rlhf-training | low | medium |
| Anthropic Claude API | claude, claude-api, claude-sdk | high | high |
| OpenAI API | openai-api, gpt-api, openai-sdk | high | high |
| Gemini API | gemini, google-genai, vertex-llm | medium | medium |
| Function calling | tool calling, tool use | high | high |
| Structured outputs | json mode, json schema output | high | high |
| Pydantic | pydantic-v2, pydantic-ai | high | high |

## Agent Frameworks

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| LangGraph | langgraph | **highest** | high |
| LangChain | langchain | high | high |
| Pydantic AI | pydantic-ai | high | medium |
| OpenAI Agents SDK | agents-sdk, openai-agents | medium | medium |
| Anthropic SDK | anthropic-sdk | medium | medium |
| CrewAI | crewai | low | low |
| AutoGen | autogen | low | low |
| DSPy | dspy | medium (Databricks/Snorkel) | low |
| Google ADK | google-adk, agent-development-kit | low | low |

## MCP (Model Context Protocol)

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| MCP | model-context-protocol | **highest** | high |
| MCP server authoring | mcp-server, custom-mcp | high | high |
| Sub-agents | subagents, hierarchical agents | high | medium |
| Agent skills | claude-skills, skill-authoring | medium | low |

## Prompt & Context Engineering

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| Prompt engineering | system prompts, few-shot | high | high |
| Context engineering | context-window-management | high | medium |
| Chain-of-thought | cot, reasoning-prompts | medium | medium |
| Prompt caching | anthropic-caching, prefix-caching | medium | medium |

## RAG

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| RAG | retrieval-augmented-generation | high | high |
| Embeddings | sentence-embeddings, dense-vectors | high | high |
| Vector search | similarity-search, ann-search | high | high |
| Agentic RAG | agent-rag, retrieval-agent | high | medium |
| Graph RAG | graphrag, kg-rag | medium | low |
| Hybrid retrieval | bm25-dense-hybrid | medium | medium |
| Re-ranking | cross-encoder-rerank, cohere-rerank | medium | medium |

## Vector Databases

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| Pinecone | pinecone-db | medium | medium |
| Weaviate | weaviate-db | medium | low |
| Chroma | chromadb | medium | medium |
| pgvector | postgres-vector | medium | high |
| Qdrant | qdrant-db | medium | low |
| FAISS | faiss-index | low | medium |

## Evals

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| Eval harness | evaluation-frameworks, golden-set | **highest** | high |
| LLM-as-judge | llm-judge, model-graded-eval | high | medium |
| DeepEval | deepeval-library | medium | low |
| Ragas | ragas-eval | medium | low |
| Regression eval | regression-test-agents | medium | medium |

## Observability

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| Langfuse | langfuse-tracing | high | high |
| LangSmith | langsmith-tracing | high | medium |
| Braintrust | braintrust-eval | medium | medium |
| Arize | arize-phoenix | medium | low |
| Galileo | galileo-eval | low | low |
| HoneyHive | honeyhive-tracing | low | low |
| Patronus | patronus-eval | low | low |
| OpenTelemetry | otel, otel-llm | medium | medium |

## Durable Execution / Workflow

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| Temporal | temporal-io | medium | **high (Ramp)** |
| Inngest | inngest-functions | low | medium |
| Modal | modal-com, modal-cron | medium | medium |
| Restate | restate-dev | low | low |
| LangGraph checkpointing | sqlite-checkpointer | high | medium |

## Multi-Agent & Coordination

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| ReAct | react-loop | medium | medium |
| Self-reflection | self-critique, reflection-pattern | medium | low |
| Hierarchical delegation | supervisor-agent, orchestrator | medium | medium |
| Agent-as-tool | agent-tool-pattern | medium | low |

## Human-in-the-Loop

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| HiTL | human-in-the-loop, approval-gate | high | medium |
| Interrupt/resume | langgraph-interrupt, checkpoint-resume | high | medium |
| Escalation patterns | confidence-escalation | medium | medium |

## Production Concerns

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| Cost per run | token-budgets, cost-instrumentation | high | high |
| Latency budgets | p50-p95-latency, tokens-per-sec | high | medium |
| Response streaming | sse-streaming, llm-streaming | medium | medium |
| Retry / idempotency | retry-logic, idempotent-tools | medium | high |
| Prompt injection defense | injection-mitigation | medium | medium |
| Guardrails | guardrails-ai, nemo-guardrails, lakera | medium | low |

## Cloud

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| AWS Bedrock | bedrock-agents | medium | high |
| AWS Lambda | lambda-serverless | medium | medium |
| Azure AI Foundry | azure-openai-foundry | low | medium |
| GCP Vertex AI | vertex-ai, vertex-agents | medium | medium |
| BigQuery | bq, gcp-bq | low | medium |

## Deployment

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| Docker | containers, dockerfile | high | high |
| Kubernetes | k8s | medium | medium |
| FastAPI | fastapi-server | high | high |
| Serverless | serverless-functions | medium | medium |

## Browser / Computer Use

| Canonical | Synonyms | Tier-2 | Tier-3 |
|---|---|---|---|
| Browserbase | browserbase-stagehand | low | low |
| Stagehand | stagehand-browser | low | low |
| Playwright | pw, playwright-py | medium | medium |
| Computer Use API | claude-computer-use | low | low |

## Voice Stack (optional — skip unless voice-targeting)

| Canonical | Tier-2 | Tier-3 |
|---|---|---|
| Vapi | medium (voice cos only) | low |
| Retell | medium (voice cos only) | low |
| Livekit | medium | low |
| Deepgram | medium | low |
| ElevenLabs | medium | low |
| Twilio | low | medium |

## Fine-Tuning (awareness only)

| Canonical | Tier-2 | Tier-3 |
|---|---|---|
| SFT | low | low |
| LoRA | low | low |
| RLHF | low | low |
| DPO | low | low |

## Fundamentals (whiteboard-level — Tier 1 only)

Transformer architecture, attention, positional encoding, KV cache, continuous batching, speculative decoding, quantization, scaling laws (Chinchilla), Constitutional AI. Tracked but not gap-aggregated — these are interview-prep, not JD keywords.
