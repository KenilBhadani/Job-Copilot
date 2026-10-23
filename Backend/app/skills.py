"""Skill extraction.

A curated list of skills + word-boundary matching. It is deterministic, free,
fast and easy to debug. To teach it a new skill, add it to TAXONOMY:
{canonical name: [aliases, all lowercase]}.
"""
from __future__ import annotations

import re
from collections import Counter

TAXONOMY: dict[str, list[str]] = {
    # Languages
    "Python": ["python"],
    "JavaScript": ["javascript", "js", "ecmascript"],
    "TypeScript": ["typescript"],
    "Java": ["java"],
    "Go": ["golang"],
    "Rust": ["rust"],
    "C++": ["c++"],
    "C#": ["c#"],
    "SQL": ["sql"],
    "Scala": ["scala"],
    "Kotlin": ["kotlin"],
    # Backend
    "FastAPI": ["fastapi"],
    "Flask": ["flask"],
    "Django": ["django"],
    "Node.js": ["node.js", "nodejs", "node js"],
    "Express": ["express.js", "expressjs"],
    "Spring Boot": ["spring boot", "springboot"],
    "REST APIs": ["rest api", "rest apis", "restful"],
    "GraphQL": ["graphql"],
    "gRPC": ["grpc"],
    "Microservices": ["microservices", "microservice"],
    "System Design": ["system design", "distributed systems"],
    # Frontend
    "React": ["react", "react.js", "reactjs"],
    "Next.js": ["next.js", "nextjs"],
    "Vue": ["vue", "vue.js"],
    "Angular": ["angular"],
    "HTML/CSS": ["html", "css", "html5", "css3"],
    "Tailwind CSS": ["tailwind", "tailwindcss", "tailwind css"],
    "Redux": ["redux"],
    # Data stores
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb"],
    "Redis": ["redis"],
    "Elasticsearch": ["elasticsearch", "opensearch"],
    "Vector Databases": ["vector database", "vector databases", "vector db", "pgvector",
                         "pinecone", "weaviate", "qdrant", "milvus", "chroma", "faiss"],
    "Kafka": ["kafka"],
    "Snowflake": ["snowflake"],
    "Spark": ["spark", "pyspark", "apache spark"],
    "Airflow": ["airflow"],
    "dbt": ["dbt"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    # AI / ML
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"],
    "PyTorch": ["pytorch"],
    "TensorFlow": ["tensorflow"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "Hugging Face": ["hugging face", "huggingface", "transformers"],
    "LLMs": ["llm", "llms", "large language model", "large language models"],
    "RAG": ["rag", "retrieval-augmented generation", "retrieval augmented generation"],
    "Embeddings": ["embeddings", "embedding models"],
    "Prompt Engineering": ["prompt engineering", "prompt design"],
    "Fine-tuning": ["fine-tuning", "fine tuning", "finetuning", "lora", "qlora", "peft"],
    "AI Agents": ["ai agent", "ai agents", "agentic", "agentic ai", "multi-agent",
                  "multi agent", "autonomous agents"],
    "LangChain": ["langchain"],
    "LangGraph": ["langgraph"],
    "LlamaIndex": ["llamaindex", "llama index"],
    "MCP": ["mcp", "model context protocol"],
    "LLM Evaluation": ["evals", "llm evaluation", "model evaluation", "ragas", "deepeval"],
    "MLOps": ["mlops", "llmops"],
    "OpenAI API": ["openai api", "gpt-4", "gpt-4o"],
    "Claude API": ["claude api", "anthropic api", "claude"],
    # Cloud / DevOps
    "AWS": ["aws", "amazon web services"],
    "Azure": ["azure"],
    "GCP": ["gcp", "google cloud"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "CI/CD": ["ci/cd", "ci cd", "continuous integration", "github actions", "jenkins"],
    "Linux": ["linux"],
    "Git": ["git", "github", "gitlab"],
    "Observability": ["observability", "opentelemetry", "prometheus", "grafana", "datadog"],
    # Practice
    "Testing": ["unit testing", "pytest", "jest", "test automation", "integration testing"],
    "Agile": ["agile", "scrum"],
}

# Reverse lookup: "k8s" -> "Kubernetes". Each canonical name also maps to itself.
ALIAS_TO_SKILL: dict[str, str] = {a: s for s, aliases in TAXONOMY.items() for a in aliases}
for _s in TAXONOMY:
    ALIAS_TO_SKILL.setdefault(_s.lower(), _s)

# One regex that finds any alias as a whole word. The (?<!...) and (?!...) parts stop
# "java" matching inside "javascript" and "sql" matching inside "postgresql".
# Longest aliases are tried first so "machine learning" wins over "ml".
_PATTERN = re.compile(
    r"(?<![a-z0-9+#.])("
    + "|".join(re.escape(a) for a in sorted(ALIAS_TO_SKILL, key=len, reverse=True))
    + r")(?![a-z0-9+#])"
)


def canonicalize(name: str) -> str:
    """Map a free-text skill (e.g. 'k8s') to its canonical name ('Kubernetes')."""
    return ALIAS_TO_SKILL.get(name.strip().lower(), name.strip())


def extract_skills(text: str) -> list[str]:
    """Canonical skills found in text, most-mentioned first."""
    counts = Counter(ALIAS_TO_SKILL[m.group(1)] for m in _PATTERN.finditer(text.lower()))
    return [s for s, _ in counts.most_common()]


# --- Job descriptions: split required vs preferred -------------------------------

_PREF_HEAD = re.compile(r"nice[\s-]to[\s-]have|preferred|bonus|good to have|extra credit|what would impress")
_REQ_HEAD = re.compile(
    r"^(requirements?|qualifications?|minimum qualifications?|must[\s-]have|required|"
    r"responsibilit|about you|who you are|what you('|’)?ll need|what we('|’)?re looking for)"
)
_PLUS = re.compile(r"\b(?:is|are|would be|will be) (?:a |an )?(?:plus|bonus|advantage)\b")
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*(?:years|yrs)")


def classify_job_skills(text: str) -> tuple[list[str], list[str]]:
    """Return (required, preferred) skills for a job description.

    Heuristic: lines under a 'nice to have / preferred / bonus' heading, or sentences
    containing 'is a plus', count as preferred. Everything else is required.
    """
    required: Counter[str] = Counter()
    preferred: Counter[str] = Counter()
    mode = "required"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower().rstrip(":").strip()
        is_heading = len(low) < 80
        if is_heading and _PREF_HEAD.search(low):
            mode = "preferred"
            continue
        if is_heading and _REQ_HEAD.match(low):
            mode = "required"
            continue
        target = preferred if (mode == "preferred" or _PLUS.search(low)) else required
        for s in extract_skills(line):
            target[s] += 1
    req = [s for s, _ in required.most_common()]
    pref = [s for s, _ in preferred.most_common() if s not in required]
    return req, pref


def min_years_required(text: str) -> int | None:
    """Smallest 'N years of experience' figure mentioned in the job text."""
    found: list[int] = []
    for line in text.splitlines():
        low = line.lower()
        if "experience" in low and ("year" in low or "yrs" in low):
            m = _YEARS.search(low)
            if m and 0 < int(m.group(1)) <= 15:
                found.append(int(m.group(1)))
    return min(found) if found else None


def years_of_experience(resume_text: str) -> float | None:
    """Best-effort 'N years of experience' from a resume (largest stated figure)."""
    found: list[int] = []
    for line in resume_text.splitlines():
        low = line.lower()
        if "experience" in low or "exp" in low:
            for m in re.finditer(r"(\d{1,2})\s*\+?\s*(?:years|yrs)", low):
                if 0 < int(m.group(1)) <= 40:
                    found.append(int(m.group(1)))
    return float(max(found)) if found else None