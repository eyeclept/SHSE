
# Self-Hosted Search Engine (SHSE)

## Overview

SHSE is a configurable, homelab-focused search engine using **Nutch** and **Elasticsearch** for crawling and indexing local services. It supports both full-text BM25 search and a simple web interface for querying and browsing results. The system is designed to be resource-conscious, with parallelism controls and configurable crawl schedules.

Key components:

- **Apache Nutch** – Crawling and text extraction (Tika embedded)
- **Elasticsearch** – Indexing and search
- **Python Controller** – Config-driven CLI for crawling and scheduling
- **Flask Web App** – Minimal search interface and results display
- **MariaDB** – For metadata, last crawl times, or authentication

---

## Features

- Configurable services and IP ranges via `config.ini`
- Supports crawl scheduling and frequency per service
- Parallelism control for both auto and manual crawls
- CLI commands for targeted or full crawls:
  ```bash
  python shse.py crawl -a
  python shse.py crawl -ip 172.27.72.20
````

* Logs crawl progress and errors
* Minimal web interface for searching and viewing results

---

## Installation (Development)

1. Clone the repository:

   ```bash
   git clone <repo-url>
   cd shse
   ```

2. Install Python requirements:

   ```bash
   pip install -r requirements.txt
   ```

3. Ensure **Docker** is installed for Nutch and Elasticsearch (or use manual installs if preferred). Mount volumes for persistent data.

4. Configure services and IP ranges in `config.ini`:

   ```ini
   [settings]
   max_parallel_jobs = 2
   auto_scan_parallel = True

   [services]
   service1 = http://172.27.72.10/wiki,weekly,wiki,none
   service2 = http://172.27.72.20/blog,daily,blog,basic

   [ip_range_scan]
   range = 10.0.0.0/16
   frequency = weekly
   ```

5. Start the Flask web app for search interface:

   ```bash
   python app.py
   ```

6. Run the Python controller to crawl services:

   ```bash
   python shse.py crawl -a
   ```

---

## Usage

* **Full crawl**: Crawl all services and IP ranges as defined in config:

  ```bash
  python shse.py crawl -a
  ```

* **Targeted crawl**: Crawl a single service or IP:

  ```bash
  python shse.py crawl -ip 172.27.72.20
  ```

* Web interface: Access via Flask app to perform searches against the Elasticsearch index.

---

## Architecture

```
[Python Controller / Scheduler]
          │
          ├── Reads config.ini
          │
          ├── Generates Nutch crawl jobs
          │
          ├── Manages job queue / parallelism
          │
          └── Invokes Nutch (Docker or host)
                  │
                  └── Crawls services, extracts text (Tika)
                          │
                          └── Indexes documents into Elasticsearch
                                  │
                                  └── Search queries served via Flask Web App
```

* Auto-scans run parallel for lightweight jobs.
* Manual or initial full crawls respect `max_parallel_jobs` for resource control.

---

## License

Apache License 2.0 – see [LICENSE](LICENSE)

````

---

### requirements.txt

```text
Flask>=2.3
requests>=2.31
concurrent-log-handler>=0.9.19
configparser>=5.3
````

* Minimal set for CLI, config reading, HTTP fetches (if needed), Flask web app.
* Add Nutch / Elasticsearch client libraries if you later integrate Python indexing/search commands.

---
