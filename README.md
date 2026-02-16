# SHSE: Self-Hosted Search Engine

SHSE is a local-first search engine designed for homelab environments.
It indexes self-hosted services (wikis, forums, internal sites, documents) and provides a Google-style search experience — with optional local AI-powered summaries via Ollama.

The project is built to run fully offline.

---

## Project Goals

* Provide a classic Google-style search interface for local infrastructure
* Support structured indexing via Elasticsearch (BM25)
* Add semantic search and RAG capabilities using Ollama
* Remain fully self-hosted and privacy-respecting
* Modular architecture allowing incremental feature development

---

## Architecture Overview

```
                ┌─────────────────────┐
                │   Data Sources      │
                │─────────────────────│
                │  ZIM (Alpha)       │
                │  Local Crawler     │
                │  Self-hosted Sites │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │ Elasticsearch Index │
                │─────────────────────│
                │  BM25 (main search)│
                │  Dense Vectors     │
                │  Metadata fields   │
                └──────────┬──────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
  Main Search (BM25)  Related Results   RAG Pipeline
                       (Embeddings)      (Ollama LLM)
                           │                │
                           └──────┬─────────┘
                                  ▼
                          Flask Web UI
```

---

# Roadmap

Development is divided into four phases:

* **Alpha** – Minimal skeleton to enable iteration
* **MVP** – Functional Google-style search interface
* **Production** – Full RAG integration with LLM
* **Stretch** – Advanced enhancements

---

# Feature Matrix

| Feature                                | Related To     | Phase      | Description                               |
| -------------------------------------- | -------------- | ---------- | ----------------------------------------- |
| Search input (terminal)                | Search Engine  | Alpha      | Basic query input                         |
| BM25 indexing/search                   | Search Engine  | Alpha      | Elasticsearch keyword search              |
| ZIM parser → Elastic                   | Data / Crawler | Alpha      | Static content ingestion                  |
| Terminal result output                 | UI             | Alpha      | URL + snippet display                     |
| Flask Web UI (basic)                   | UI             | MVP        | Simple search form + results              |
| Snippet preview (basic)                | Search Engine  | MVP        | First-line preview with keyword highlight |
| Pagination (basic)                     | Search Engine  | MVP        | Page-based result navigation              |
| Basic operators (`"quotes"`, `site:`)  | Search Engine  | MVP        | Simple field filtering                    |
| Time-based filtering (basic)           | Search Engine  | MVP        | Filter by indexed timestamp               |
| Local network crawler (basic)          | Data / Crawler | MVP        | Replace ZIM with HTML crawler             |
| Metadata display (title, URL, favicon) | UI             | MVP        | Standard search result formatting         |
| Embeddings for semantic retrieval      | LLM / RAG      | Production | Dense vectors stored in Elastic           |
| Multi-source retrieval                 | LLM / RAG      | Production | Combine multiple indexed sources          |
| AI Overview (Ollama RAG)               | LLM / RAG      | Production | Generated summary using retrieved context |
| Prompt engineering                     | LLM / RAG      | Production | Style control for AI output               |
| Autocomplete / query suggestions       | Search Engine  | Stretch    | Predictive search suggestions             |
| Related results sidebar (vector)       | Search Engine  | Stretch    | Semantic related links                    |
| Advanced operators                     | Search Engine  | Stretch    | filetype:, combined operators             |
| Rich snippet formatting                | Search Engine  | Stretch    | Context windows + advanced highlighting   |
| Advanced ranking tuning                | Search Engine  | Stretch    | Custom scoring adjustments                |
| Advanced time filters                  | Search Engine  | Stretch    | Multi-range UI filters                    |

---

# Search Strategy

## Main Results (Core Search)

* Powered by **BM25**
* Optimized for:

  * Exact matches
  * Query operators
  * Snippet highlighting
  * Pagination
  * Ranking

This mirrors classic pre-AI Google behavior.

## Related Results (Sidebar)

* Powered by **vector embeddings**
* Semantic similarity search
* Displays a small number of related documents

## AI Overview (Production Phase)

* Query → embedding retrieval → top chunks
* Context fed to Ollama LLM
* Concise generated summary shown above results

---

# Data Ingestion Strategy

### Alpha

* ZIM parser extracts Wikipedia content
* Chunks indexed into Elasticsearch

### MVP

* Replace ZIM with local network crawler
* Crawl:

  * HTML pages
  * Self-hosted wikis/forums
  * Basic document types

### Production

* Improved metadata extraction
* Multi-source aggregation
* Robust crawling logic

---

# Technology Stack

| Component     | Technology              |
| ------------- | ----------------------- |
| Search Engine | Elasticsearch           |
| Backend       | Python                  |
| Web Interface | Flask                   |
| Crawling      | Custom crawler (MVP)    |
| AI / LLM      | Ollama                  |
| Embeddings    | Ollama embedding models |

---

# Design Principles

* Local-first
* Modular components
* Separation of concerns:

  * Search (BM25)
  * Semantic retrieval (vectors)
  * Generation (LLM)
* Progressive enhancement roadmap
* Minimal external dependencies

---

# License

SHSE is released under the GNU General Public License (GPL).

---

# Installation

TBD

---

# Requirements

TBD

---

# Configuration

TBD

---

