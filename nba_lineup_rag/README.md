# NBA Lineup Intel RAG (GenAI HW 1 - Yu-Sen Wu)

**Tech Stack: Python + ChromaDB + LangChain + E5-large-v2**

A Retrieval-Augmented Generation (RAG) system for NBA player injury and lineup information.

## 📊 RAG Evaluation Report

See the complete comparison and evaluation results of RAG approaches:

[![View RAG Evaluation Report](https://img.shields.io/badge/查看-RAG_評估報告-blue?style=for-the-badge)](./RAG_evaluation.pdf)

---

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Data Sources](#data-sources)
- [Environment Setup](#environment-setup)
- [ChromaDB Setup](#chromadb-setup)
- [Data Ingestion & Processing](#data-ingestion--processing)
- [Vector DB Querying](#vector-db-querying)
- [RAG Method Comparison](#rag-method-comparison)
- [Testing & Usage](#testing--usage)
- [Python API Examples](#python-api-examples)
- [FAQ](#faq)

---

## Features

### Part 1: Vector Database

1. **Real-time Data Collection**: Fetches data from ESPN RSS news and ESPN/CBS injury pages.
2. **Raw Data Storage**: Stores raw data in JSONL format, supporting replay and re-indexing.
3. **Smart Processing Pipeline**: Cleansing → Normalization → Deduplication → Chunking.
4. **Vector Embeddings**: Uses E5-large-v2 model (1024 dimensions).
5. **ChromaDB Storage**: Persistent vector storage with metadata filtering.
6. **Semantic Query**: Supports filtering by team/player/date.

### Part 2: Advanced RAG

7. **LangChain Integration**: Complete LangChain RAG workflow.
8. **HyDE (Hypothetical Document Embedding)**: Improves retrieval by generating hypothetical docs.
9. **Reranking**: Two-stage retrieval, using Cross-Encoder for reranking.
10. **Evaluation Framework**: Compares four methods - LLM-only, Simple RAG, HyDE, Reranking.

---

## Project Structure

```
nba_lineup_rag/
├── data/                           # Data directory (auto-created at runtime)
│   ├── raw/                        # Raw data (JSONL format)
│   │   ├── espn_rss/               # ESPN RSS news
│   │   └── injuries_pages/         # Injury page data
│   ├── processed/                  # Processed documents
│   └── chroma/                     # ChromaDB persistent storage
│
├── src/                            # Core code
│   ├── __init__.py
│   ├── config.py                   # Config management (env vars, paths, defaults)
│   ├── logging_utils.py            # Logging utilities
│   │
│   ├── sources/                    # Data source modules
│   │   ├── espn_rss.py             # ESPN RSS fetcher
│   │   └── injuries_pages.py       # ESPN/CBS injuries page scraper
│   │
│   ├── processing/                 # Data processing docs
│   │   ├── chunking.py             # Text chunking (recursive splitter)
│   │   ├── dedupe.py               # Deduplication logic (SHA256 hash)
│   │   ├── extract_entities.py     # Entity extraction (team/player/date/status)
│   │   └── normalize.py            # Text normalization (HTML cleanup, spaces)
│   │
│   ├── embeddings/                 # Embedding modules
│   │   └── e5_embedder.py          # E5-large-v2 embedder
│   │
│   ├── vectordb/                   # ChromaDB operations
│   │   ├── chroma_client.py        # ChromaDB client mgmt
│   │   ├── collections.py          # Collection mgmt (3 collections)
│   │   ├── query.py                # Query engine (multi-collection search)
│   │   └── upsert.py               # Data insert/update
│   │
│   └── rag/                        # RAG inference modules
│       ├── answer.py               # Basic RAG (Part 1)
│       ├── langchain_rag.py        # LangChain RAG (Part 2)
│       ├── hyde.py                 # HyDE implementation (Part 2)
│       ├── reranker.py             # Reranking logic (Part 2)
│       ├── e5_langchain.py         # E5 LangChain wrapper
│       └── prompts.py              # Prompt templates
│
├── scripts/                        # Executable scripts
│   ├── ingest_all.py               # Main data ingestion
│   ├── ingest_source.py            # Single-source ingestion
│   ├── query_cli.py                # CLI query tool
│   ├── evaluate_rag.py             # RAG evaluation script (Part 2)
│   ├── rebuild_index_from_raw.py   # Rebuild index from raw data
│   ├── inspect_vectordb.py         # DB inspection tool
│   ├── debug_injuries_scraper.py   # Scraper debugging tool
│   └── eval_smoke.py               # Smoke test
│
├── notebooks/                      # Jupyter Notebooks
│   └── part2_evaluation.ipynb      # Evaluation notebook (Part 2)
│
├── examples/                       # Example scripts
│   └── inspect_example.py          # Usage example
│
├── outputs/                        # Evaluation outputs (Part 2)
├── requirements.txt                # Python requirements
├── .env.example                    # Example environment variables
├── .gitignore                      # Git ignore rules
└── test_vectordb.sh                # Vector DB test script
```

---

## Data Sources

The system fetches real-time NBA information from the following three sources:

| Source           | URL                                         | Update Frequency   | Data Type      |
|------------------|---------------------------------------------|--------------------|----------------|
| ESPN NBA RSS     | https://www.espn.com/espn/rss/nba/news      | Every 3–5 minutes  | News articles  |
| ESPN Injuries    | https://www.espn.com/nba/injuries           | Every 10–30 mins   | Injury reports |
| CBS Injuries     | https://www.cbssports.com/nba/injuries/     | Every 10–30 mins   | Injury reports |

### How Data Is Collected

**ESPN RSS (`src/sources/espn_rss.py`):**
- Uses `feedparser` to parse the RSS feed.
- Uses `requests` to fetch full article content.
- Uses `readability-lxml` to extract main content.
- Stores as JSONL, with deduplication via hashing.

**Injury Pages (`src/sources/injuries_pages.py`):**
- Uses `BeautifulSoup` + `lxml` to parse HTML.
- Extracts player injury info from HTML tables.
- Extracts: team, player name, position, status, injury description.
- Normalizes team names to standard abbreviations.

---

## Environment Setup

### 1. Create a Virtual Environment

```bash
# Create a virtual environment
python -m venv venv

# Activate the virtual environment
source venv/bin/activate     # macOS / Linux
# Or
venv\Scripts\activate        # Windows
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

**Key Dependencies Overview:**

| Package                      | Purpose                                 |
|------------------------------|-----------------------------------------|
| `chromadb>=0.5.0`            | Vector DB for storing/searching vectors |
| `sentence-transformers>=3.0.0`| Embedding model loading/inference      |
| `torch>=2.1.0`               | PyTorch deep learning framework         |
| `langchain>=0.3.0`           | LLM app framework                       |
| `langchain-openai>=0.2.0`    | LangChain & OpenAI integration          |
| `langchain-chroma>=0.1.0`    | LangChain & ChromaDB integration        |
| `openai>=1.0.0`              | OpenAI API client                       |
| `beautifulsoup4>=4.12.0`     | HTML parsing                            |
| `feedparser>=6.0.0`          | RSS parsing                             |
| `readability-lxml>=0.8.1`    | Web content extraction                  |
| `rapidfuzz>=3.9.0`           | Fuzzy string matching                   |

### 3. Configure Environment Variables

```bash
# Copy environment variable template
cp .env.example .env

# Edit the .env file with your API key
```

**`.env` file:**

```env
# ===========================================
# NBA Lineup Intel RAG - Environment Config
# ===========================================

# Data directory settings
CHROMA_DIR=data/chroma           # ChromaDB storage directory
RAW_DIR=data/raw                 # Raw data directory
PROCESSED_DIR=data/processed     # Processed data directory

# Network request settings
USER_AGENT=nba-lineup-rag-bot/1.0
TIMEZONE=America/Chicago

# OpenAI API Key (required for Part 2)
OPENAI_API_KEY=sk-your-api-key-here

# Embedding model settings
EMBEDDING_MODEL=intfloat/e5-large-v2   # Use E5-large-v2 model
EMBEDDING_DEVICE=cpu                   # Or cuda (if you have GPU)

# Chunking settings
CHUNK_SIZE=1000      # Characters per chunk
CHUNK_OVERLAP=150    # Characters of overlap between chunks
```

**Environment Variable Description:**

| Variable         | Required?     | Default             | Description                                  |
|------------------|--------------|---------------------|----------------------------------------------|
| `OPENAI_API_KEY` | Required (P2) | -                   | OpenAI API key for LLM inference             |
| `CHROMA_DIR`     | Optional      | `data/chroma`       | ChromaDB persistence directory               |
| `EMBEDDING_MODEL`| Optional      | `intfloat/e5-large-v2`| Embedding model name                       |
| `EMBEDDING_DEVICE`| Optional     | `cpu`               | Inference device, can set to `cuda`          |
| `CHUNK_SIZE`     | Optional      | `1000`              | Text chunk size                              |
| `CHUNK_OVERLAP`  | Optional      | `150`               | Chunk overlap size                           |

---

## ChromaDB Setup

### ChromaDB Overview

ChromaDB is an open-source vector database used here for:
- Storing document embeddings
- Semantic search
- Metadata filtering

### Storage Mode

This project uses **PersistentClient** (persistent client):

```python
# src/vectordb/chroma_client.py
self._client = chromadb.PersistentClient(
    path=self.chroma_dir,  # Default: data/chroma
    settings=Settings(
        anonymized_telemetry=False,  # Disable telemetry
    )
)
```

- **Storage location**: `data/chroma/`
- **Storage format**: SQLite DB
- **Feature**: Data persists and is kept after restarting the app

### Collection Structure

Three collections are used to store different types of data:

| Collection Name      | Data Source           | Priority   | Default top_k |
|---------------------|-----------------------|------------|---------------|
| `nba_news`          | ESPN RSS articles     | 3 (lowest) | 5             |
| `nba_injuries_pages`| ESPN/CBS injury pages | 2          | 6             |
| `nba_injury_reports`| Official reports      | 1 (highest)| 8             |

**Similarity metric:** Cosine similarity (`hnsw:space: cosine`)

### Collection Initialization

Collections are created automatically during the first data ingestion run:

```bash
# Automatically creates all collections
python scripts/ingest_all.py --since 6h
```

Or initialize manually:

```python
from src.vectordb.collections import get_collection_manager

# Ensure all collections are present
manager = get_collection_manager()
manager.ensure_all_collections()
```

### Inspecting ChromaDB State

```bash
# View DB stats
python scripts/inspect_vectordb.py stats

# Browse data (show top 5 entries)
python scripts/inspect_vectordb.py browse --limit 5

# Test queries
python scripts/inspect_vectordb.py test-query --q "Lakers injury"
```

---

## Data Ingestion & Processing

### Full Data Ingestion Flow

```bash
# 1. Ingest all sources from last 6 hours
python scripts/ingest_all.py --since 6h

# 2. Full data ingest (no time limit)
python scripts/ingest_all.py --full

# 3. Ingest specific sources only
python scripts/ingest_all.py --sources espn_rss
python scripts/ingest_all.py --sources injuries_pages
python scripts/ingest_all.py --sources espn_rss,injuries_pages
```

### Data Processing Pipeline

```
┌─────────────┐
│   Source    │
│ ESPN/CBS    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Fetch      │  ← Fetch webpage/RSS
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Raw Store  │  ← Store as JSONL (data/raw/)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Normalize  │  ← HTML cleanup, whitespace cleanup
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Extract    │  ← Extract team/player/date/status
│  Entities   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Chunking   │  ← Split (1000 chars, 150 overlap)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Embedding  │  ← E5-large-v2 (1024 dim)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  ChromaDB   │  ← Persist to storage
└─────────────┘
```

### Ingest a Single Source

```bash
# Ingest ESPN RSS only
python scripts/ingest_source.py --source espn_rss

# Ingest injury pages only
python scripts/ingest_source.py --source injuries_pages
```

### Rebuilding the Index

If you update chunking settings or processing logic, rebuild the index from raw data:

```bash
# Rebuild all indexes from raw data
python scripts/rebuild_index_from_raw.py

# Rebuild specific source
python scripts/rebuild_index_from_raw.py --source espn_rss

# Reset and rebuild (deletes all current data)
python scripts/rebuild_index_from_raw.py --reset
```

---

## Vector DB Querying

### CLI Query Tool

```bash
# Basic query
python scripts/query_cli.py --q "Is LeBron playing tonight?"

# Add team filter
python scripts/query_cli.py --team LAL --q "injury update"

# Add player filter
python scripts/query_cli.py --player "Stephen Curry" --q "latest news"

# Adjust returned results
python scripts/query_cli.py --q "NBA injuries" --k 5

# Show detailed result info
python scripts/query_cli.py --q "Lakers news" --verbose

# Interactive mode
python scripts/query_cli.py --interactive
```

### Interactive Mode Commands

In interactive mode, you can use:

```
Commands:
  Type a natural language question to query
  /team LAL      - Set team filter
  /player LeBron - Set player filter
  /clear         - Clear all filters
  /exit or /quit - Exit
```

### Sample Query Results

```
Query: Is LeBron playing tonight?
Team filter: LAL

Found 3 relevant result(s):
============================================================

[1] Score: 0.8542 | Source: nba_injuries_pages
    Team: LAL
    Player(s): LeBron James
    Date: 2026-02-03T12:30:00Z
    Content: LeBron James (LAL) - Forward - Status: Probable. 
             Injury: Left ankle soreness. Expected to play...

------------------------------------------------------------

[2] Score: 0.7891 | Source: nba_news
    Team: LAL
    Title: Lakers Injury Report: LeBron Listed as Probable...
    Date: 2026-02-03T10:15:00Z
    Content: The Los Angeles Lakers have released their injury 
             report ahead of tonight's game...
```

---

## RAG Method Comparison

### Four RAG Methods

| Method         | Description                              | Pros         | Cons            |
|----------------|------------------------------------------|--------------|-----------------|
| **LLM Only**   | Just GPT-4o-mini, no retrieval           | Fast         | No real-time info |
| **Simple RAG** | Vector retrieval + LLM                   | Up-to-date   | Query-doc semantic gap |
| **HyDE**       | Generate hypothetical doc, then retrieve | Better semantic match | Extra LLM call |
| **Reranking**  | Two-stage retrieval + Cross-Encoder      | Best ranking | Slower          |

### Running RAG Evaluation

```bash
# Full evaluation (4 methods × 5 questions)
python scripts/evaluate_rag.py

# Evaluate a single question
python scripts/evaluate_rag.py --question "Is LeBron playing tonight?"

# Evaluate only selected methods
python scripts/evaluate_rag.py --methods llm_only simple_rag
python scripts/evaluate_rag.py --methods hyde reranking

# All methods:
# llm_only, simple_rag, hyde, reranking
```

### Using Jupyter Notebook

```bash
# Launch Jupyter and open the eval notebook
jupyter notebook notebooks/part2_evaluation.ipynb
```

---

## Testing & Usage

### Quick Test

```bash
# 1. Run vector DB test script
chmod +x test_vectordb.sh
./test_vectordb.sh

# 2. Run smoke test
python scripts/eval_smoke.py
```

### Full Workflow

```bash
# Step 1: Set up environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# Step 2: Install dependencies
pip install -r requirements.txt

# Step 3: Ingest data and build index
python scripts/ingest_all.py --since 6h

# Step 4: Check DB stats
python scripts/inspect_vectordb.py stats

# Step 5: Test a query
python scripts/query_cli.py --q "Who is injured on the Lakers?"

# Step 6: Run RAG evaluation (OPENAI_API_KEY required)
python scripts/evaluate_rag.py
```

### Inspecting DB Content

```bash
# Show stats
python scripts/inspect_vectordb.py stats

# Example output:
# Total collections: 3
# Collections:
#   nba_news: 125 documents
#   nba_injuries_pages: 89 documents
#   nba_injury_reports: 0 documents

# Browse a specific collection
python scripts/inspect_vectordb.py browse --collection nba_injuries_pages --limit 10

# Search test
python scripts/inspect_vectordb.py test-query --q "Lakers injury" --k 5
```

---

## Python API Examples

### Basic Query

```python
from src.vectordb.query import QueryEngine

# Create query engine
engine = QueryEngine()

# Run a query
results = engine.query(
    question="Is LeBron playing tonight?",
    team="LAL",           # Optional: team filter
    player="LeBron",      # Optional: player filter
    top_k=10              # Number of documents to return
)

# Process results
for r in results:
    print(f"Score: {r.score:.4f}")
    print(f"Collection: {r.collection}")
    print(f"Team: {r.metadata.get('team')}")
    print(f"Content: {r.text[:200]}...")
    print("---")
```

### LangChain RAG

```python
from src.rag import (
    LangChainRAG,
    query_llm_only,
    query_simple_rag,
)

# Method 1: LLM Only (no retrieval)
result1 = query_llm_only("Is LeBron playing tonight?", team="LAL")
print(result1["answer"])

# Method 2: Simple RAG (vector retrieval + LLM)
result2 = query_simple_rag("Is LeBron playing tonight?", team="LAL")
print(result2["answer"])
print(f"Used {len(result2['sources'])} source documents")
```

### HyDE RAG

```python
from src.rag import HyDERetriever, query_with_hyde

# Use HyDE for query
result = query_with_hyde("Is LeBron playing tonight?", team="LAL")
print(result["answer"])
print(f"Hypothetical doc: {result['hypothetical_doc'][:100]}...")
```

### Reranking RAG

```python
from src.rag import RerankedRAG, query_with_rerank

# Use Reranking for query
result = query_with_rerank("Is LeBron playing tonight?", team="LAL")
print(result["answer"])
print(f"Reranked {len(result['reranked_docs'])} documents")
```

### Compare All Methods

```python
from src.rag import (
    query_llm_only,
    query_simple_rag,
    query_with_hyde,
    query_with_rerank,
)

question = "Is LeBron playing tonight?"
team = "LAL"

# Run all methods
methods = {
    "LLM Only": query_llm_only,
    "Simple RAG": query_simple_rag,
    "HyDE": query_with_hyde,
    "Reranking": query_with_rerank,
}

for name, func in methods.items():
    print(f"\n=== {name} ===")
    result = func(question, team=team)
    print(result["answer"][:200] + "...")
```

### Direct ChromaDB Access

```python
from src.vectordb import get_chroma_client
from src.vectordb.collections import get_collection_manager

# Get ChromaDB client
client = get_chroma_client()

# List all collections
collections = client.list_collections()
for coll in collections:
    print(f"{coll.name}: {client.get_collection(coll.name).count()} documents")

# Get specific collection
collection = client.get_collection("nba_injuries_pages")

# Query (must provide embedding)
from src.embeddings import E5Embedder
embedder = E5Embedder()
query_embedding = embedder.embed_query("Lakers injury update")

results = collection.query(
    query_embeddings=[query_embedding],
    n_results=5,
    where={"team": "LAL"},  # metadata filter
)

print(results["documents"])
print(results["metadatas"])
```

---

## FAQ

### Q1: Model download is slow on first run?

E5-large-v2 model is about 1.3GB and will be automatically downloaded from Hugging Face the first time:

```
Downloading (…)/model.safetensors: 100%|██████| 1.34G/1.34G
```

After download, it will be cached at `~/.cache/huggingface/` so you don't have to redownload.

### Q2: CUDA out of memory error?

Edit `.env` to use CPU:

```env
EMBEDDING_DEVICE=cpu
```

### Q3: OpenAI API call failing?

Ensure `OPENAI_API_KEY` in `.env` is set correctly:

```env
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxx
```

### Q4: ChromaDB data corruption?

Delete `data/chroma` and re-ingest:

```bash
rm -rf data/chroma
python scripts/ingest_all.py --full
```

### Q5: How do I reset all data?

```bash
# Delete all data
rm -rf data/

# Re-ingest
python scripts/ingest_all.py --since 24h
```

### Q6: Query results not accurate?

Try the following:
1. Increase data: `python scripts/ingest_all.py --full`
2. Use more context: increase the `--k` parameter
3. Try HyDE or Reranking methods

### Q7: How to add new data sources?

1. Add a new fetcher in `src/sources/`
2. Add a collection to `src/vectordb/collections.py`
3. Add ingestion logic in `scripts/ingest_all.py`

---

## License

This project is a coursework assignment for Northwestern MLDS 424.

---

## References

- [ChromaDB Documentation](https://docs.trychroma.com/)
- [LangChain Documentation](https://python.langchain.com/)
- [E5 Embedding Model](https://huggingface.co/intfloat/e5-large-v2)
- [Sentence Transformers](https://www.sbert.net/)
