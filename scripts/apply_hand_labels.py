"""One-shot: write hand-labels (expected_score + expected_skills + notes) onto
the 30 records in labeled_dataset.json.

Labels were produced by reading each JD against `_profile/resume.md`,
`_profile/role-clarifications.md`, and `_profile/skill-inventory.md`. The
scoring rubric mirrors `compass/pipeline/nodes/score.py`'s `_SYSTEM_PROMPT`:
0 = wrong field, 1 = poor skill match, 2 = stretch, 3 = decent match, 4 =
strong match with evidence, 5 = exact stack at the right seniority. YoE nudge
(small, offsettable) and category-mismatch penalty applied per the prompt.

The labels reflect the candidate's role-clarifications constraints:
- FDE/customer-facing pre-sales is the explicit gap → caps strong-stack FDE
  roles around 2.0–3.0
- Not frontend specialist, not embedded, not EM, not LC/system-design strong
- Strong cluster: MCP (level 4), agents (level 3), LangGraph (level 3),
  Python (level 3); weak: RAG/observability/vector DBs (Compass closes)

User should review and edit any label they disagree with — these are my best
read, not the user's lived self-assessment.
"""

from __future__ import annotations

import json
from pathlib import Path

DATASET = Path(__file__).resolve().parents[1] / "compass" / "evals" / "labeled_dataset.json"

LABELS: dict[str, tuple[float, list[str], str]] = {
    # (expected_score, expected_skills, notes)
    # Inclusive lens: score for target-role-fit and learnable concepts.
    # "Particularly X" / "such as X" / "including X" are examples not gates;
    # bonus/nice-to-have can only push UP. Real penalties only for category
    # mismatch (FE specialist, embedded, EM, CSE) or multi-year skills
    # (CUDA, Rust systems, on-device, clearance, staff-level).
    "eval-001": (
        3.25,
        ["Python", "JavaScript", "LangChain", "LangGraph", "LLM evaluation",
         "observability", "guardrails", "MCP", "AWS", "GCP", "Azure",
         "Kubernetes", "containers", "agent design"],
        "Strong stack match (Python, MCP, LangGraph). Deployed-Engineer "
        "is FDE-adjacent but the technical stack overlap is exact and the "
        "candidate's MCP team-adoption work is real customer-impacting "
        "context. YoE gap closes via exact-stack signal.",
    ),
    "eval-002": (
        3.5,
        ["Python", "TypeScript", "LangChain", "LangGraph", "LangSmith", "RAG",
         "AI agents", "retrieval", "cognitive architectures", "prompt engineering",
         "LLM systems"],
        "Exact-stack tier-2 agent role; 'GTM Engineer' framed as internal-"
        "build / first-customer / builder-operator (not pre-sales). LangGraph "
        "+ LangSmith + agents is Compass's exact toolchain.",
    ),
    "eval-003": (
        2.0,
        ["Python", "JavaScript", "TypeScript", "React", "Next.js", "shadcn",
         "Node.js", "RAG", "LLMs", "AI agents", "prompt engineering", "Docker",
         "Kubernetes", "Terraform", "Google Cloud Run"],
        "Fullstack with frontend lead. Has real LLM/RAG/agent overlap from "
        "Compass work but JD explicitly requires React-based front-end work "
        "at production scale — frontend specialization is the category gate.",
    ),
    "eval-004": (
        1.25,
        ["Python", "PyTorch", "vLLM", "TGI", "TensorRT-LLM", "CUDA", "Triton",
         "Rust", "Cython", "compilers", "low-level OS", "multi-threading",
         "networking", "speculative decoding"],
        "Inference-engine role; CUDA + low-level OS are multi-year skills, "
        "not learnable in interview-prep window. Python+PyTorch overlap is "
        "minimal here.",
    ),
    "eval-005": (
        1.5,
        ["Java", "distributed systems", "multi-threaded applications"],
        "Java-primary role; candidate has Java at coursework level. "
        "2+ yr ask is the only thing that fits.",
    ),
    "eval-006": (
        3.25,
        ["Python", "JavaScript", "LangChain", "LangGraph", "AWS", "GCP", "Azure",
         "Kubernetes", "Docker", "LLM evaluation", "observability", "guardrails",
         "agent design"],
        "Same as eval-001 with Bay Area location. Deployed-Engineer is FDE-"
        "adjacent but exact-stack overlap is strong.",
    ),
    "eval-007": (
        0.75,
        ["Adobe Experience Manager", "AEM as Cloud Service", "Edge Delivery "
         "Services", "full-stack development", "AI experimentation"],
        "AEM is a hard requirement; candidate has zero AEM exposure. AI "
        "curiosity overlaps but isn't the gate.",
    ),
    "eval-008": (
        1.25,
        ["GenAI", "RAG", "multi-agent systems", "Text2SQL", "fine-tuning",
         "HuggingFace", "LangChain", "DSPy", "pandas", "scikit-learn", "PyTorch",
         "AWS", "Azure", "GCP", "Databricks platform", "Apache Spark"],
        "US Secret clearance is a hard gate. DMV-area on-site. FDE explicitly "
        "out-of-scope per role-clarifications even if those passed.",
    ),
    "eval-009": (
        3.5,
        ["Java", "Python", "LLMs", "AI agents", "agent tools", "agent skills",
         "LangChain", "LlamaIndex", "Semantic Kernel", "Google ADK",
         "prompt engineering", "prompt tuning", "ML model evaluation", "MLOps",
         "Faiss", "Chroma", "vector databases", "microservices",
         "distributed systems", "Kafka", "Cassandra", "Azure", "AWS", "GCP",
         "Docker", "Kubernetes", "responsible AI", "agile",
         "AI-native code editors"],
        "Associate level (2+ yr) fits. AI/ML reqs: 8-9/10 with production "
        "evidence — production MCP work maps 1:1 to 'AI Agents, agent tools, agent "
        "skills'; LangGraph + Chroma + prompt engineering all shipped via "
        "Compass; Cursor tooling work covers AI-native IDE req. Core eng: "
        "Python ('particularly Java and Python' — Python qualifies), AWS "
        "('Azure preferred; AWS acceptable'), SQL+MongoDB ('including "
        "Cassandra' — Cassandra is an example, not a gate). Real gaps are "
        "Java (coursework only), Kafka and distributed systems (conceptual). "
        "Strong-match band per rubric.",
    ),
    "eval-010": (
        4.25,
        ["Python", "LangGraph", "Pydantic AI", "DSPy", "MCP", "async Python",
         "structured concurrency", "distributed tracing", "vector databases",
         "Chroma", "Pinecone", "Weaviate", "RAG", "prompt caching",
         "model routing", "structured output", "evaluation", "Langfuse",
         "LangSmith"],
        "The exact role this portfolio was built for. MCP + LangGraph + "
        "Pydantic AI + Chroma + Langfuse + eval harness — every primary "
        "requirement met with shipped evidence. YoE gap fully offset.",
    ),
    "eval-011": (
        2.75,
        ["Python", "JavaScript", "TypeScript", "RAG", "BM25", "vector search",
         "AI agents", "prompt engineering", "evaluation", "guardrails", "AWS",
         "GCP", "Azure", "containers", "Kubernetes", "reasoning loops"],
        "FDE / Forward-Deployed role; not the target track but the technical "
        "stack overlap is real (RAG + agents + Python + evaluation). 'Bias "
        "for action / ship v0.1 and iterate' framing fits builder profile.",
    ),
    "eval-012": (
        0.5,
        ["Python", "C++", "Rust", "CUDA", "Triton", "GPU programming", "PyTorch",
         "vLLM", "TGI", "TensorRT-LLM", "quantization", "AWQ", "GPTQ", "FP8",
         "distillation", "technical leadership"],
        "Staff IC + 8+ yr + GPU/CUDA + leads a team. Wrong role-family + wrong "
        "level + wrong stack.",
    ),
    "eval-013": (
        0.25,
        ["C", "C++", "embedded software", "FreeRTOS", "Zephyr", "real-time OS",
         "ARM", "kinematics", "ROS2", "ISO 26262"],
        "Embedded firmware; on-site Pittsburgh; entirely wrong field.",
    ),
    "eval-014": (
        0.5,
        ["TypeScript", "React", "rich-text editors", "Slate", "Lexical",
         "ProseMirror", "CSS", "accessibility", "CRDTs", "OT", "WebSockets",
         "React Native", "Electron"],
        "Senior frontend specialist (6+ yr editor framework experience). "
        "Anti-claim: not a frontend specialist.",
    ),
    "eval-015": (
        0.5,
        ["engineering management", "Python", "Spark", "Airflow", "dbt",
         "Snowflake", "AWS"],
        "EM role with 3+ yr formal management. Management track is explicitly "
        "out of scope.",
    ),
    "eval-016": (
        3.75,
        ["Python", "LLM systems", "LangGraph", "DSPy", "AI agents",
         "agentic workflows", "retrieval pipelines", "evaluation harnesses",
         "fine-tuning", "prompt tuning", "LLM-as-judge", "regression sets"],
        "MTS Applied AI at a frontier lab — exact target. Every primary "
        "requirement met (Python, LangGraph, agents, eval methodology). "
        "Frontier-lab bar nudges slightly down; offset by Compass shipping.",
    ),
    "eval-017": (
        2.25,
        ["Java", "Python", "Scala", "data structures", "algorithms", "OOP",
         "financial systems"],
        "Rotational program; YoE band fits (0-2). Finance domain and LC-style "
        "loop are off-target. Rotational format gives optionality.",
    ),
    "eval-018": (
        1.25,
        ["Python", "TypeScript", "technical communication", "account "
         "management", "webhook debugging"],
        "Customer Success Engineer; non-engineering primary role. Anti-claim: "
        "not customer-facing in a sales sense.",
    ),
    "eval-019": (
        1.25,
        ["Python", "Rust", "Go", "containers", "runc", "gVisor", "Firecracker",
         "Linux kernel internals", "eBPF", "gRPC", "distributed storage",
         "AWS Lambda", "GCP Cloud Run", "Cloudflare Workers"],
        "5+ yr distributed systems + container internals + Rust/Go. Python "
        "is the only overlap; everything else is a gap.",
    ),
    "eval-020": (
        4.0,
        ["Python", "Java", "Go", "TypeScript", "LLMs", "AI agents", "LangChain",
         "LangGraph", "Pydantic AI", "DSPy", "evaluation", "datasets",
         "Kubernetes", "gRPC", "distributed tracing"],
        "L4 agentic platform at big-tech cloud — L4 (2+ yr) "
        "fits. Python + agent SDK + eval service work all map directly to "
        "the candidate's MCP and Compass work. Second-language ask (Java/Go/TS) is 'and one "
        "of' — Java coursework satisfies; would tighten before interview.",
    ),
    "eval-021": (
        0.75,
        ["C++", "Swift", "Objective-C", "Rust", "PyTorch", "JAX", "TensorFlow",
         "Core ML", "Metal", "CUDA", "NPU SDKs", "memory management",
         "performance profiling"],
        "On-device ML frameworks; Swift/Obj-C/custom silicon. Candidate has "
        "PyTorch only; no Swift, no on-device, no custom silicon. JD even "
        "says this role does NOT focus on agents.",
    ),
    "eval-022": (
        1.75,
        ["Python", "Kubernetes", "Ray", "Spark", "Slurm", "Airflow", "MLOps",
         "model serving", "feature stores", "monitoring", "vLLM", "TGI",
         "sglang", "llm-d", "ML evaluation"],
        "5+ yr MLOps + cluster ops (Ray/Spark/Slurm). MLOps experience is "
        "a real gap, not learnable in interview prep. Python overlap exists "
        "but doesn't carry the role.",
    ),
    "eval-023": (
        0.75,
        ["Rust", "C++", "Elasticsearch", "Lucene", "Tantivy", "Vespa", "Lance",
         "DuckDB", "distributed systems", "consensus", "replication", "sharding",
         "embedding retrieval", "LangChain", "Pydantic AI", "MCP"],
        "Founding engineer + 7+ yr + Rust/C++ + DB internals. Hopelessly "
        "out-of-band on YoE, languages, and prior systems work.",
    ),
    "eval-024": (
        2.5,
        ["Python", "Django", "FastAPI", "Flask", "PostgreSQL", "SQL", "AWS",
         "Redis", "Kafka", "SQS", "event-driven architectures"],
        "Generic backend SaaS. Python + Flask + SQL overlap; not the target "
        "track (no agents/LLM). 5+ yr ask is a real gap. Fintech is a soft "
        "preference, not a gate.",
    ),
    "eval-025": (
        0.5,
        ["Java", "Go", "Rust", "C++", "service mesh", "gRPC", "observability",
         "vLLM", "TGI", "Triton Inference Server", "LLM serving", "CUDA",
         "PyTorch internals"],
        "Senior L6, 7+ yr, JVM/Go/Rust/C++, foundation-model hosting at "
        "hyperscaler. Far above-level + wrong languages.",
    ),
    "eval-026": (
        0.25,
        ["Swift", "SwiftUI", "iOS", "macOS", "App Store", "mobile development"],
        "iOS junior frontend; anti-claim is not a frontend specialist + no "
        "Swift + in-person NYC 5 days.",
    ),
    "eval-027": (
        2.75,
        ["Python", "TypeScript", "Go", "CLI", "SDK", "developer-facing API",
         "technical writing", "DevRel", "open-source maintainership",
         "LLM SDKs", "agent SDKs"],
        "DX/DevRel role at a developer-platform company; LLM/agent SDK work "
        "(Compass MCP server + personal projects) is direct overlap. Public-facing DevRel "
        "is a partial gap but the JD frames the role as build-and-ship "
        "developer ergonomics, not pure advocacy.",
    ),
    "eval-028": (
        4.25,
        ["Python", "async Python", "typed Python", "LLMs", "AI agents",
         "LangGraph", "Pydantic AI", "DSPy", "MCP", "prompt engineering",
         "evaluation methodology", "vector databases", "RAG"],
        "Junior agent-eng at vertical AI startup — 0-3 yr band "
        "is exact; MCP at junior level is a strong differentiator; "
        "LangGraph + Pydantic AI + evals all shipped via Compass.",
    ),
    "eval-029": (
        3.25,
        ["Python", "pandas", "polars", "DuckDB", "Spearman", "MAE",
         "bootstrapping", "multi-judge agreement", "LLM evaluation", "HELM",
         "lm-eval-harness", "Inspect AI", "LangSmith", "Langfuse", "Braintrust"],
        "Research Engineer (Eval) — Compass eval harness IS this JD's "
        "primary ask (cross-family judge, ensemble aggregation, Spearman/MAE "
        "reporting). Pandas/polars/DuckDB are 1-week ramps. Statistical "
        "rigor demonstrated by the existing methodology trajectory.",
    ),
    "eval-030": (
        1.5,
        ["SQL", "dbt", "Snowflake", "BigQuery", "Redshift", "Python", "Airflow",
         "Dagster", "HL7", "FHIR", "Kafka", "Flink"],
        "Senior Data Engineer (5+ yr) in healthcare. SQL + Snowflake from "
        "prior-employer overlap; dbt/Airflow/Dagster/healthcare formats are gaps. "
        "Data-eng is an adjacent track, not the agentic-AI portfolio target.",
    ),
}


def main() -> int:
    existing = json.loads(DATASET.read_text(encoding="utf-8"))
    updated = 0
    for record in existing:
        rid = record["id"]
        if rid not in LABELS:
            print(f"  skip {rid}: no label provided")
            continue
        score, skills, notes = LABELS[rid]
        record["expected_score"] = score
        record["expected_skills"] = skills
        record["notes"] = notes
        updated += 1

    # Atomic write: a SIGKILL mid-write would otherwise truncate the JSON
    # and break every subsequent `load_dataset()` call. Mirrors the
    # `compass.evals.dataset.save_dataset()` pattern.
    import os as _os

    tmp = DATASET.with_suffix(DATASET.suffix + ".tmp")
    tmp.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _os.replace(tmp, DATASET)
    print(f"updated {updated} records with hand-labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
