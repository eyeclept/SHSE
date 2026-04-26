# Fixtures

JSON snapshots of the data each route renders with. Use them to:

- **Render templates without a backend** — load the JSON in a route stub
  and pass it straight to `render_template(...)`. Lets you visually check
  templates while plumbing isn't done yet.
- **Anchor pytest fixtures** — `tests/conftest.py` can monkeypatch your
  query layer to return these blobs.
- **Communicate the contract** — every key/shape the templates expect is
  documented here; treat them as the source of truth for "what does the
  template need".

## Files

| File | Used by |
|---|---|
| `search_results.json` | `templates/search.html` + `templates/_result_item.html` |
| `history.json` | `templates/history.html` |
| `admin_overview.json` | `templates/admin/index.html` + `templates/admin/_health_grid.html` |
| `admin_targets.json` | `templates/admin/targets.html` |
| `admin_jobs.json` | `templates/admin/jobs.html` + `templates/admin/_jobs_rows.html` |
| `admin_config.json` | `templates/admin/config.html` + `templates/admin/_yaml_validation.html` |
| `admin_index_ops.json` | `templates/admin/index_ops.html` |

## Quick demo wiring

In `app.py`:

```python
import json, pathlib
FIXT = pathlib.Path(__file__).parent / "fixtures"

def _fixture(name):
    return json.loads((FIXT / f"{name}.json").read_text())

@app.route("/search")
def search():
    data = _fixture("search_results")
    data["q"] = request.args.get("q", data.get("q", ""))
    return render_template("search.html", **data)
```

Replace each `_fixture(...)` call with the real query during the
corresponding sprint. Delete the fixture once the route uses live data
(or keep it under `tests/fixtures/` for pytest).
