# Results API

`meridian serve` publishes completed result bundles over HTTP so that dashboards and
notebooks can read them without access to the results folder. The API is read-only for
bundles: it never changes, deletes or writes result files.

## Starting the server

```bash
export MERIDIAN_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m meridian serve --results results --port 8765
# Serving results on http://127.0.0.1:8765 (Ctrl+C to stop)
```

| Option | Default | Meaning |
|---|---|---|
| `--results` | `results` | Folder holding result bundles, as written by `meridian run` |
| `--host` | `127.0.0.1` | Address to listen on; the default only accepts local connections |
| `--port` | 8765 | Port to listen on |

The API key is read from `MERIDIAN_API_KEY` and must be at least 16 characters. The server
refuses to start without one. To accept connections from other machines, set `--host` to
the machine's address and put the server behind an HTTPS reverse proxy; the server itself
speaks plain HTTP.

## Authentication

Every endpoint except `/health` needs the key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: $MERIDIAN_API_KEY" http://127.0.0.1:8765/results
```

A missing or wrong key gets `401` with `{"error": "Missing or invalid API key"}`. Keys are
compared in constant time.

## Endpoints

### `GET /health`

Liveness check for monitoring. No key needed.

```json
{"status": "ok"}
```

### `GET /results`

Completed bundles in the results folder, newest first. Folders without a completion
marker, or whose files fail the integrity check, are left out.

| Query parameter | Default | Meaning |
|---|---|---|
| `product` | all | Only bundles with at least one lane of this product (`nitrogen`, `oxygen` or `argon`) |
| `limit` | 20 | Return at most this many bundles, from 1 to 100 |

```json
[
  {
    "name": "baseline-1a2b3c4d5e6f",
    "scenario_id": "baseline",
    "horizon_days": 60,
    "total_mean_cost": 48210.4,
    "portfolio_fill_rate": 0.962,
    "lanes": 6
  }
]
```

### `GET /results/<name>`

One bundle's complete `summary.json`, after the same integrity checks as
`meridian compare`. `name` is the bundle folder name from `GET /results`. Add
`?product=oxygen` to keep only that product's lane rows. Unknown names, and names that
are not bundle folder names, get `404`.

### `POST /what-if/capacity`

Shares proposed daily plant capacities between a bundle's product-locations, to show
which sites would be short if production were limited.

Request body:

```json
{
  "bundle": "baseline-1a2b3c4d5e6f",
  "capacities": {"nitrogen": 1200, "argon": 100},
  "product": "nitrogen"
}
```

| Field | Required | Meaning |
|---|---|---|
| `bundle` | yes | Bundle folder name |
| `capacities` | yes | Proposed capacity per product, in kg per day |
| `product` | no | Only return allocations for this product |
| `priorities` | no | Priority weight per lane, such as `{"Harbor:nitrogen": 2}`; unlisted lanes have weight 1 |

Response:

```json
{
  "bundle": "baseline-1a2b3c4d5e6f",
  "scenario_id": "baseline",
  "allocations": [
    {
      "lane": "Harbor:nitrogen",
      "product": "nitrogen",
      "demand_kg": 800.0,
      "allocated_kg": 662.1,
      "shortfall_kg": 137.9,
      "coverage": 0.828
    }
  ],
  "summary": {
    "lanes": 3,
    "demand_kg": 1450.0,
    "allocated_kg": 1200.0,
    "shortfall_kg": 250.0,
    "lanes_short": 3,
    "coverage": 0.828
  }
}
```

Errors: `400` for a body that is not a JSON object, a missing `bundle` or an unknown
`product`; `404` for an unknown bundle; `422` for invalid capacities, such as a negative
value or an unknown product name.

## How capacity is shared

Demand per lane is the mean daily demand recorded in the bundle's inputs, multiplied by
the run's `demand_multiplier`, so it matches the demand that was simulated.

For each product with a proposed capacity:

1. Capacity is shared between that product's lanes in proportion to their daily demand
   multiplied by their priority weight. Without `priorities`, every lane has weight 1 and
   capacity follows demand alone. A lane with weight 2 receives twice the share per kg
   of demand of a lane with weight 1.
2. No lane receives more than its demand. Capacity a lane cannot use is shared again,
   in the same proportions, between the lanes that still need more.
3. When capacity is at least total demand, every lane is fully covered.

Lanes of products without a proposed capacity are left out of the response. A lane with
zero demand receives nothing and is reported as fully covered.

This is a steady-state check of daily volumes. It does not re-run the simulation, so it
says nothing about inventory or timing; use it to find which sites to study further with
a full scenario.

## Using the API from Python

```python
import json
import os
from urllib.request import Request, urlopen

key = os.environ["MERIDIAN_API_KEY"]
body = json.dumps({"bundle": "baseline-1a2b3c4d5e6f", "capacities": {"nitrogen": 1200}})
request = Request(
    "http://127.0.0.1:8765/what-if/capacity",
    data=body.encode(),
    method="POST",
    headers={"X-API-Key": key, "Content-Type": "application/json"},
)
with urlopen(request, timeout=10) as response:
    print(json.load(response)["summary"])
```

The same allocation is available without the server, from the command line:

```bash
python -m meridian what-if results/baseline-1a2b3c4d5e6f/summary.json \
  --capacity nitrogen=1200 --capacity argon=100
```

or from Python:

```python
from meridian.bundles import verify_bundle
from meridian.whatif import allocate, allocation_summary, lane_demands

report = verify_bundle("results/baseline-1a2b3c4d5e6f/summary.json")
allocations = allocate(lane_demands(report), {"nitrogen": 1200})
print(allocation_summary(allocations))
```
