"""One-shot helper: append 21 synthetic JDs to labeled_dataset.json so the
eval harness runs at n=30 instead of n=9.

The JDs are plausible synthesizations across tier-2 agent-eng startups, tier-3
big-tech, infra/ML systems, generic SaaS SWE, and out-of-scope roles. They
are deliberately fictional — no real target companies — so the public eval
results don't disclose the candidate's targeting strategy. Judge-mode is the
intended path: expected_score/expected_skills are placeholders; the LLM judge
produces the labels on the fly.
"""

from __future__ import annotations

import json
from pathlib import Path

DATASET = Path(__file__).resolve().parents[1] / "compass" / "evals" / "labeled_dataset.json"


JDS: list[tuple[str, str]] = [
    # (source-label, jd_text)
    (
        "synth-AgentLab — Senior Agent Engineer (tier-2 agentic startup)",
        """About AgentLab
We build production agent infrastructure for enterprise customers. Our platform handles
multi-step tool use, long-running workflows, and reliable execution at scale.

About the role
Senior Engineer, Agent Platform. You will own the runtime that executes agent graphs
in production — checkpointing, retries, sandboxed tool execution, observability.

What you'll do
- Design and ship the core agent runtime (Python). Stateful graphs, conditional edges,
  durable checkpointing, human-in-the-loop interrupts.
- Build the evaluation harness — both offline (regression suites) and online (LLM-judge
  scoring on live traces).
- Integrate with our customers' tool ecosystems via the Model Context Protocol (MCP).
- Improve cost and latency: prompt caching, model routing, structured output.

What we're looking for
- 3+ years building production systems in Python.
- Experience shipping LLM-powered features end to end — not prototypes, real users.
- Hands-on with at least one agent framework (LangGraph, Pydantic AI, DSPy, etc.).
- Comfort with async Python, structured concurrency, distributed tracing.
- Strong eval discipline — you've built or significantly contributed to an LLM eval suite.

Nice to have
- Open-source contributions to the agent / LLM tooling ecosystem.
- Experience with vector databases (Chroma, Pinecone, Weaviate) and RAG pipelines.
- MCP server or client implementations.
- Langfuse, LangSmith, or similar observability stacks.

Compensation: $190K–$260K + equity.
""",
    ),
    (
        "synth-Mosaic — Forward Deployed AI Engineer (tier-2 applied AI)",
        """About Mosaic
We help Fortune 500 customers ship internal copilots and domain-specific agents.

The role
Forward Deployed Engineer. You work alongside customer engineering teams to design,
build, and deploy bespoke LLM applications — RAG systems, knowledge agents, workflow
automations — using our platform.

Responsibilities
- Scope and architect customer projects end to end. Translate vague business goals into
  concrete agent architectures.
- Implement: prompt engineering, retrieval (BM25 + vector hybrid), evaluation, guardrails.
- Be on the front line of production: latency tuning, cost analysis, debugging weird
  model failures.
- Feed learnings back into the core product — file issues, write design docs, push PRs.

Requirements
- 4+ years software engineering, with at least 1 year shipping LLM features in production.
- Strong Python. JavaScript / TypeScript also useful.
- Comfortable with customer-facing technical work — POCs, architecture reviews, demos.
- Bias for action; you'd rather ship a v0.1 and iterate than spec for 3 weeks.

Bonus
- Experience with cloud platforms (AWS / GCP / Azure), containers, K8s.
- Prior FDE / forward-deployed / solutions-engineering background.
- Have built non-trivial agent systems with reasoning loops.

Salary: $200K–$280K + equity. Hybrid SF or NYC.
""",
    ),
    (
        "synth-Spire — Staff Engineer, Cloud Inference Platform (ML infra)",
        """The team
Spire's inference platform serves billions of LLM tokens per day to enterprise customers.
We are looking for a Staff Engineer to lead next-generation inference optimization.

Responsibilities
- Drive the technical roadmap for our inference runtime: batching, KV-cache management,
  speculative decoding, multi-model serving.
- Own deep performance work in CUDA / Triton kernels and PyTorch.
- Lead a team of 4 engineers. Hands-on coding expected (~50% of time).
- Partner with the research org to land new model architectures in production within
  weeks of release.

Requirements
- 8+ years software engineering, with 3+ years on high-performance systems (inference,
  training, HPC, or systems-level ML).
- Expert in Python and at least one of C++ / Rust.
- Deep knowledge of GPU programming (CUDA, Triton, or equivalent).
- Track record leading technical efforts across an org.

Strongly preferred
- Direct experience with vLLM, TGI, TensorRT-LLM, or comparable inference frameworks.
- Familiarity with quantization (AWQ, GPTQ, FP8) and distillation.
- Open-source contributions in the ML systems space.

Compensation: $300K–$420K base + equity + bonus.
""",
    ),
    (
        "synth-Helix Robotics — Embedded Engineer (out-of-scope hardware role)",
        """Helix Robotics — Embedded Software Engineer

We build autonomous warehouse robots. You will own firmware on the robot's perception
and motion-control subsystems.

What you'll do
- Write embedded C/C++ for our custom ARM-based control boards.
- Bring up new sensor stacks (LiDAR, ToF cameras, IMU).
- Profile and tune real-time control loops running at 1 kHz.
- Work directly with mechanical and electrical engineers on the hardware bring-up.

Requirements
- 5+ years embedded software development.
- Expert in C and C++17 for resource-constrained environments.
- Real-time OS experience (FreeRTOS, Zephyr).
- Comfort reading schematics and using a logic analyzer / oscilloscope.

Nice to have
- ROS2.
- Functional safety standards (ISO 26262 or equivalent).
- Kinematics / control theory background.

Onsite in Pittsburgh, PA. No remote.
Compensation: $170K–$220K.
""",
    ),
    (
        "synth-Quill — Senior Frontend Engineer (tier-2 SaaS, frontend-focused)",
        """Quill — Senior Frontend Engineer

We're building the future of collaborative writing. You will lead frontend architecture
on our flagship editor.

What you'll do
- Own the rich-text editor stack (Slate / Lexical / ProseMirror). Performance,
  accessibility, plugin architecture.
- Build complex realtime collaboration UI on top of our CRDT backend.
- Mentor a team of 4 frontend engineers; lead frontend hiring loop.
- Partner with design to ship industry-leading interactions.

Requirements
- 6+ years frontend engineering, with 3+ years on rich editor / canvas / collaborative apps.
- Deep TypeScript, React, modern build tooling.
- Strong CSS chops — animations, layout, accessibility.
- Experience with realtime collaboration (CRDTs, OT, WebSockets) is a hard requirement.

Nice to have
- Experience with React Native or Electron.
- Open-source contributions to a major editor framework.

$200K–$260K + equity. Remote-friendly (US time zones).
""",
    ),
    (
        "synth-Northwind — Engineering Manager (out-of-scope management role)",
        """Northwind — Engineering Manager, Data Platform

We're hiring an EM to lead a team of 7 engineers building the data ingestion + transform
platform that powers our analytics product.

You will
- Own delivery: roadmap, sprint planning, on-call rotations, cross-team coordination.
- Run hiring loops, do performance reviews, develop senior engineers into staff engineers.
- Partner with product to translate business priorities into engineering plans.
- Drive technical direction at the team level, though IC work is rare (~10%).

We're looking for
- 8+ years total software experience, with 3+ years in a formal management role.
- Track record of growing engineers and shipping platform work on time.
- Strong technical foundation (you can read code reviews, push back on bad designs).
- Calm under pressure during incidents.

Tech we use: Python, Spark, Airflow, dbt, Snowflake, AWS. Familiarity is helpful, but
deep expertise is not required.

$240K–$310K base + equity.
""",
    ),
    (
        "synth-Lumen AI — Applied AI Engineer (tier-3 frontier lab applied)",
        """Lumen AI — Member of Technical Staff, Applied AI

Our Applied AI org partners with frontier-model research and customer-facing product
teams. You will build internal tools and customer-facing prototypes that turn frontier
capabilities into shipped product.

Day to day
- Build prototypes: agentic workflows, retrieval pipelines, evaluation harnesses, custom
  fine-tunes for specific verticals.
- Translate fuzzy product asks into concrete LLM-powered systems. Ship in days, not months.
- Work directly with model researchers to surface deployment-time issues that should
  feed back into training.
- Establish evaluation methodology for shipped features. We take eval discipline seriously
  — LLM-as-judge, hand-labeled regression sets, online metrics.

Required
- 3+ years building production software in Python.
- Demonstrated experience shipping LLM-powered features beyond simple prompting.
- Familiarity with at least one agent framework (LangGraph, DSPy, etc.) or having
  built a meaningful agent system from primitives.
- Strong written communication — design docs, post-mortems.

Bonus
- Open-source contributions in the LLM tooling space.
- Experience with our model API. Direct experience tuning prompts for our largest models.
- Background in evaluation methodology (psychometrics, statistics).

Comp: $230K–$340K + significant equity.
""",
    ),
    (
        "synth-BigBank — Software Engineer III, Rotational (out-of-scope finance entry)",
        """BigBank Technology — Software Engineer III, Rotational Program

Join our rotational engineering program. New hires rotate through 3 teams over 18 months
across Trading Tech, Risk Platform, and Consumer Banking.

In the program you will
- Spend 6 months on each rotation. Write production code in Java, Python, or Scala
  depending on the team.
- Pair with senior engineers on real production systems. Ship features that move metrics.
- Build a network across the org — mentorship from VPs, exec speaker series.

We are looking for
- Bachelor's in CS or related; 0–2 years of professional engineering experience.
- Strong fundamentals: data structures, algorithms, OOP.
- Curiosity about financial systems. Prior finance experience NOT required.
- US citizenship or permanent residency (required for our regulated business lines).

What we offer
- Full-time conversion to a specific team at the end of the program.
- $130K–$165K base + sign-on bonus + 401k match.
- NYC, Jersey City, or Charlotte offices. Hybrid (3 days in-office).
""",
    ),
    (
        "synth-Verge AI — Customer Success Engineer (out-of-scope CS role)",
        """Verge AI — Customer Success Engineer

We are looking for a CSE to be the technical face of Verge for our top accounts.

You will
- Own technical onboarding: walk customers through integration, write sample code, debug
  webhook issues.
- Run quarterly business reviews; surface usage patterns and growth opportunities.
- Be the voice of the customer internally — file tickets, push for feature work, write
  internal docs on integration patterns.
- Travel to customer offices ~30% of the time.

Requirements
- 3+ years in a technical customer-facing role (CSE, SE, support engineer, technical PM).
- Comfortable reading and writing simple Python / TypeScript scripts. Not expected to
  ship production features.
- Excellent written + verbal communication.
- Track record managing accounts with $100K+ ARR.

Nice to have
- Past experience at a developer-tools company.
- Familiarity with our API or with LLM APIs more broadly.

OTE: $180K–$240K. Remote-friendly.
""",
    ),
    (
        "synth-Modal-style — Senior Engineer, Distributed Systems (tier-2 infra)",
        """Senior Engineer — Distributed Compute Platform

We run a serverless platform that lets developers run Python functions on remote GPUs
with zero infrastructure. Millions of containers per day.

You will
- Own one of: the container scheduler, the storage layer, the function-call gateway, or
  the streaming I/O subsystem.
- Build for scale: our worst-case latency targets are P99 < 200ms for cold-starts.
- Lead non-trivial cross-team projects end to end.
- Work in our codebase that's predominantly Python with Rust performance hotspots.

Requirements
- 5+ years building production distributed systems.
- Expert in at least one of Python, Rust, Go.
- Deep familiarity with one or more of: containers (runc, gVisor, Firecracker), Linux
  kernel internals, networking (eBPF, gRPC), distributed storage.
- Comfortable working in a fast-moving codebase with sparse documentation.

Bonus
- Open-source contributions in adjacent infrastructure projects.
- Prior experience at hyperscaler / cloud infrastructure (AWS Lambda, GCP Cloud Run,
  Cloudflare Workers).

$240K–$340K base + significant equity.
""",
    ),
    (
        "synth-BigTech-Cloud — L4 Software Engineer, Agentic AI Platform (tier-3 big tech)",
        """L4 Software Engineer, Agentic AI Platform

The Agentic AI Platform team at our cloud org builds the runtime, tools, and developer
SDK for agents running on our cloud. Our customers are enterprise developers building
internal copilots, customer-support agents, and workflow automations.

You will
- Build SDK and runtime features for agent developers (Python, TypeScript).
- Contribute to our managed eval service — datasets, judges, scoring infra.
- Partner with cross-functional teams (research, infra, security) to ship capabilities
  end to end.
- Write design docs, drive technical decisions, ship monthly.

Required
- 2+ years professional software engineering (SWE II / L4 level).
- Bachelor's in CS or equivalent industry experience.
- Strong Python AND one of (Java, Go, TypeScript).
- Some exposure to LLMs / agent systems — coursework, side projects, prior internship.

Preferred
- Built or significantly contributed to a non-trivial LLM-powered system.
- Familiarity with one major agent framework (LangChain / LangGraph / Pydantic AI / DSPy).
- Experience with cloud-native development (Kubernetes, gRPC, distributed tracing).

Levels: this is an L4 (mid-level) role. L5 candidates considered if hiring loop signals.
Total comp: $215K–$310K (base + RSU + bonus).
""",
    ),
    (
        "synth-BigTech-Apple — Software Engineer, On-Device AI (tier-3 big tech)",
        """Software Engineer, On-Device AI Frameworks

Our team builds the frameworks that power on-device intelligence on consumer hardware —
millions of devices running ML inference daily.

What you'll do
- Build APIs in Swift and Objective-C for app developers to integrate our models.
- Contribute to the on-device inference runtime: model conversion, kernel optimization
  for our custom silicon, memory layout, latency tuning.
- Work cross-functionally with hardware, research, and product teams.
- Ship features that ride to hundreds of millions of users on annual OS releases.

Required
- 3+ years software engineering.
- Strong systems programming background: C++, Swift, or Rust.
- Comfort with concurrent programming, memory management, performance profiling.
- Bachelor's in CS or related.

Preferred
- Experience with ML frameworks (PyTorch, JAX, TensorFlow, or Core-ML-equivalents).
- Custom-silicon programming (Metal, CUDA, NPU SDKs).
- Shipped consumer product features.

This role does not focus on LLM agents or RAG — it focuses on on-device inference and
framework engineering. If you want to work on cloud-side agent platforms, check our
other openings.

Cupertino, hybrid (3 days in-office). $200K–$280K base + RSU.
""",
    ),
    (
        "synth-Anyscale-style — Senior MLOps Engineer (tier-2 ML infra)",
        """Senior MLOps Engineer

We build the platform that lets ML teams take models from research to production.

Responsibilities
- Own the model deployment pipeline: training-to-serving handoff, A/B testing infra,
  rollback / canary, online metrics.
- Build infrastructure for LLM fine-tuning workflows on our managed cluster (Ray, Slurm).
- Contribute to the experiment-tracking + observability layer.
- Partner with customer ML teams during integration; surface friction back to product.

Requirements
- 5+ years professional software experience.
- Strong Python, comfortable contributing to a large mono-repo.
- Experience with at least two of: Kubernetes, Ray, Spark, Slurm, Airflow.
- Prior MLOps / ML platform experience — model serving, feature stores, monitoring.

Bonus
- Familiarity with LLM-specific infra (vLLM, TGI, sglang, llm-d).
- Built or contributed to an ML evaluation harness.
- Open-source in the ML/data ecosystem.

$210K–$290K + equity. Remote-first (US time zones).
""",
    ),
    (
        "synth-VectorDB — Founding Engineer, Search Infrastructure (tier-2 infra)",
        """Founding Engineer — Search Infrastructure

We are a small (12 people) team building the next-generation vector search engine,
optimized for retrieval-augmented agents. Pre-Series A.

You will
- Own a major subsystem of our search engine. Indexing, query execution, replication,
  or filtering — your choice based on background.
- Make architectural decisions that will be hard to change later. Defend them in design
  review.
- Ship to production weekly. Be on-call for the systems you own.
- Hire engineers 2–10 over the next 18 months.

Required
- 7+ years building production systems.
- Expert in Rust or C++. Comfortable with low-level performance work.
- Prior database or search-engine experience (Elasticsearch, Lucene, Tantivy, Vespa,
  Lance, DuckDB, or comparable).
- Distributed systems fundamentals: consensus, replication, sharding.

Preferred
- Built an embedding-based retrieval system in production.
- Familiar with the agent + RAG ecosystem (LangChain, Pydantic AI, MCP).
- Open-source maintainer at a data / search project.

Cash: $200K–$260K, with significant founding equity grant.
""",
    ),
    (
        "synth-Beacon — Senior Backend Engineer, Generic SaaS (tier-2 SaaS)",
        """Senior Backend Engineer

We're a 200-person SaaS company building the next-generation expense management
platform. The role is on our Core Platform team.

What you'll do
- Design and build new product features end to end. Backend-heavy: Python (Django),
  PostgreSQL, Redis, AWS.
- Improve our internal services: payment processing, identity, notifications.
- Mentor mid-level engineers. Drive code review culture.
- Participate in our weekly on-call rotation.

Required
- 5+ years backend engineering in production environments.
- Strong Python. Strong SQL. Comfortable with one of: Django, FastAPI, Flask.
- Track record of shipping complex features against tight deadlines.
- Experience designing schemas for high-throughput systems.

Nice to have
- Fintech / payment systems background.
- Familiarity with event-driven architectures (Kafka, SQS).
- Experience operating Postgres at scale (partitioning, replication).

$190K–$240K base + equity. Remote-first.
""",
    ),
    (
        "synth-Bedrock-style — Senior Engineer, Foundation Model Hosting (tier-3 hyperscaler)",
        """Senior Software Engineer — Foundation Model Hosting

Our team operates the multi-tenant inference fleet that serves frontier models inside
our cloud. We serve enterprise customers globally with SLOs measured in single-digit
milliseconds of overhead per request.

You will
- Build the routing layer that picks the right model, region, and pod for each request.
- Drive efficiency: KV-cache reuse, batching policies, multi-LoRA serving.
- Partner with model providers to land new model launches without operational drama.
- Own SLOs for one or more critical surfaces. Be in the rotation for incidents.

Required
- 7+ years SWE experience, 3+ years on large-scale distributed services.
- Expert in one of Java, Go, Rust, C++.
- Deep familiarity with cloud-native patterns: service mesh, gRPC, observability.
- Have shipped systems serving >10K QPS in production.

Nice to have
- Direct experience with LLM serving — vLLM, TGI, Triton Inference Server, or proprietary
  inference stacks.
- ML systems background (CUDA, PyTorch internals).
- Prior work in any major cloud provider's ML platform org.

L6 equivalent. $310K–$450K total comp.
""",
    ),
    (
        "synth-OpenTab — Junior Frontend Engineer (out-of-scope junior FE)",
        """Junior Frontend Engineer

OpenTab is a small company building a beautiful native iOS + macOS app for managing
restaurant operations. We're hiring our first dedicated frontend engineer.

You will
- Work primarily in Swift + SwiftUI on iPad and macOS.
- Implement designs from our design lead. Pixel-perfect, smooth animations, accessibility.
- Pair with backend engineers on API design.
- Own quality of the surfaces you ship.

Requirements
- 0–2 years professional experience or strong internship portfolio.
- Have shipped at least one personal iOS or macOS app to the App Store.
- Solid Swift fundamentals. SwiftUI strongly preferred.
- Strong sense of design and craft.

We will mentor you on testing, architecture, code review. We don't expect senior-level
output, but we expect curiosity and attention to detail.

$120K–$155K + equity. NYC office, in-person 5 days a week.
""",
    ),
    (
        "synth-DevTools-DX — Developer Experience Engineer (tier-2 devtools, generalist)",
        """Developer Experience Engineer

We build a developer platform used by 100K+ developers. The DX team owns the surfaces
those developers see daily: the CLI, SDKs (Python, TypeScript, Go), the dashboard, and
the docs.

You will
- Build features in our CLI and SDKs. Focus on ergonomics — the difference between a
  good API and a great one.
- Write reference docs, tutorials, and conceptual guides.
- Sit in on customer integrations to learn where the platform feels wrong; file issues
  and ship fixes.
- Run an open-source repo where we share examples and starter templates.

Required
- 4+ years professional engineering.
- Strong in at least two of Python, TypeScript, Go.
- Have shipped a developer-facing API or CLI you're proud of.
- Excellent technical writing.

Nice to have
- Past role in DevRel or DX at a developer-tools company.
- Open-source maintainership.
- Background working with LLM / agent SDKs (you'll integrate our platform with them).

$180K–$240K + equity. Remote-friendly.
""",
    ),
    (
        "synth-AgentCo — Junior Agent Engineer (tier-2 agentic startup, junior level)",
        """Junior Agent Engineer

AgentCo (Series A, 25 people) is building a vertical AI agent for the legal industry.

You will
- Implement new agent capabilities under the guidance of senior engineers. Tool integrations,
  retrieval improvements, evaluation cases.
- Triage failure modes from our customer-facing logs. Write reproductions, propose fixes.
- Own a small portion of the eval suite end to end.
- Pair with our founding engineering team daily.

Required
- 0–3 years professional engineering experience, OR strong intern portfolio.
- Comfortable writing Python end to end. Async / typed Python a plus.
- Have built at least one non-trivial LLM-powered side project. Show us the repo.
- Curiosity about agent architecture, prompt engineering, evaluation methodology.

Nice to have
- Familiarity with LangGraph, Pydantic AI, DSPy, or another agent framework.
- Built or contributed to an MCP server or client.
- Exposure to vector databases / RAG.

$140K–$180K + equity. In-person SF.
""",
    ),
    (
        "synth-Lattice — Research Engineer, Eval (tier-2 applied research)",
        """Research Engineer — Evaluation

We are hiring a Research Engineer focused on LLM evaluation methodology. Our team
publishes open benchmarks and operates the eval infra inside our product.

You will
- Design evaluation datasets and methodologies — both static benchmarks and dynamic
  judge-based evaluations.
- Build infra that runs evals at scale on every model release. Statistical rigor matters.
- Co-author papers on eval methodology. Speak at conferences.
- Partner with internal product teams to land evals against their use cases.

Required
- 3+ years software engineering, OR a graduate degree in CS / Statistics + 1 year SWE.
- Strong Python. Comfortable with data tooling (pandas, polars, DuckDB).
- Statistical literacy — Spearman, MAE, bootstrapping, multi-judge agreement.
- Have built or significantly contributed to an LLM eval pipeline.

Nice to have
- Published work on LLM evaluation.
- Familiarity with industry-standard eval frameworks (HELM, lm-eval-harness, Inspect AI).
- Experience with LangSmith, Langfuse, Braintrust, or similar observability platforms.

$220K–$320K + equity.
""",
    ),
    (
        "synth-Acme Health — Senior Data Engineer (out-of-scope data eng)",
        """Senior Data Engineer

Acme Health is a 600-person healthcare company. Our Data Platform team owns the
pipelines that feed analytics, reporting, and ML at the company.

You will
- Own pipelines from our 30+ source systems into our Snowflake warehouse.
- Build and maintain dbt models. Improve data quality and freshness.
- Partner with analytics + ML teams on schema design.
- Be on-call for the platform once a month.

Required
- 5+ years data engineering experience.
- Strong SQL. Strong dbt. Comfortable in Python for orchestration (Airflow / Dagster).
- Experience operating a data warehouse at scale (Snowflake, BigQuery, Redshift).
- Familiarity with healthcare data formats (HL7, FHIR) is a strong plus.

Nice to have
- HIPAA / SOC2 experience.
- Streaming ingestion (Kafka, Flink) familiarity.
- Past dbt-Labs / Snowflake summit speaker.

$180K–$235K + equity. Remote (US).
""",
    ),
]


def main() -> int:
    existing = json.loads(DATASET.read_text(encoding="utf-8"))
    start_n = len(existing)
    if start_n != 9:
        print(f"WARNING: expected 9 existing records, found {start_n}. Aborting.")
        return 1

    next_id = start_n + 1
    appended = 0
    for label, body in JDS:
        record = {
            "id": f"eval-{next_id:03d}",
            "jd_text": body.strip(),
            "source": label,
            "expected_score": 0.0,
            "expected_skills": [],
            "notes": "auto-seeded synthetic JD for judge-mode eval at n=30",
        }
        existing.append(record)
        next_id += 1
        appended += 1

    DATASET.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"appended {appended} records; dataset is now n={len(existing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
