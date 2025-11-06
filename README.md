# prometheus-remote-write-client

A lightweight, production-ready Prometheus **remote_write** metrics client for **push-based** systems.

Instead of exposing /metrics for Prometheus to scrape like prometheus_client, this client pushes metrics directly to a remote_write endpoint.
This makes it suitable for:

- Batch jobs
- Event-driven pipelines
- Serverless / Cron tasks
- Edge / Distributed systems where Prometheus cannot scrape

## Features

| Capability              | Description                                               |
| ----------------------- | --------------------------------------------------------- |
| **remote_write native** | No HTTP exporter required                                 |
| **Counters**            | Maintains monotonicity (`*_total`)                        |
| **Gauges**              | Arbitrary numeric values                                  |
| **Histograms**          | Local bucket aggregation with `_bucket`, `_sum`, `_count` |
| **Snappy + Protobuf**   | Fully compatible wire format                              |
| **Debug Mode**          | Pretty `/metrics`-style output for verification           |

Designed to be **simple, transparent, and deterministic** — no hidden state and no background threads.

## Example Usage

```python
from prometheus_remote_write_client import RemoteWriteClient

ENDPOINT = "https://prometheus/api/v1/write"

cli = RemoteWriteClient(ENDPOINT, debug=True)

# Counter
cli.counter_inc("billing_orders", 85)

# Gauges
cli.gauge_set("billing_queue_depth", 36, {"queue": "payments"})
cli.gauge_set("billing_queue_depth", 5,  {"queue": "refunds"})
cli.gauge_set("billing_queue_depth", 0,  {"queue": "dlq"})

# Histogram
now = int(time.time() * 1000)
cli.histogram_queue("billing_job_duration_seconds", 0.6,  {"worker": "billing-worker-01"}, ts=now - 120000)
cli.histogram_queue("billing_job_duration_seconds", 2.2,  {"worker": "billing-worker-01"}, ts=now - 60000)
cli.histogram_queue("billing_job_duration_seconds", 10.0, {"worker": "billing-worker-01"}, ts=now)
cli.histogram_flush("billing_job_duration_seconds", {"worker": "billing-worker-01"})

cli.histogram_queue("billing_job_duration_seconds", 0.3,  {"worker": "billing-worker-02"}, ts=now - 120000)
cli.histogram_queue("billing_job_duration_seconds", 1.2,  {"worker": "billing-worker-02"}, ts=now - 60000)
cli.histogram_queue("billing_job_duration_seconds", 8.9, {"worker": "billing-worker-02"}, ts=now)
cli.histogram_flush("billing_job_duration_seconds", {"worker": "billing-worker-02"})
```

Output in debug mode resembles `/metrics`:

```
[DEBUG] remote_write_req_seq: 1
# TYPE billing_orders_total counter
billing_orders_total 85

[DEBUG] remote_write_req_seq: 2
# TYPE billing_queue_depth gauge
billing_queue_depth{queue="payments"} 36

[DEBUG] remote_write_req_seq: 3
# TYPE billing_queue_depth gauge
billing_queue_depth{queue="refunds"} 5

[DEBUG] remote_write_req_seq: 4
# TYPE billing_queue_depth gauge
billing_queue_depth{queue="dlq"} 0

[DEBUG] remote_write_req_seq: 5
# TYPE billing_job_duration_seconds histogram
billing_job_duration_seconds_bucket{worker="billing-worker-01",le="0.5"} 0
billing_job_duration_seconds_bucket{worker="billing-worker-01",le="1"} 1
billing_job_duration_seconds_bucket{worker="billing-worker-01",le="2.5"} 2
billing_job_duration_seconds_bucket{worker="billing-worker-01",le="5"} 2
billing_job_duration_seconds_bucket{worker="billing-worker-01",le="10"} 3
billing_job_duration_seconds_bucket{worker="billing-worker-01",le="+Inf"} 3
billing_job_duration_seconds_count{worker="billing-worker-01"} 3
billing_job_duration_seconds_sum{worker="billing-worker-01"} 12.8

[DEBUG] remote_write_req_seq: 6
# TYPE billing_job_duration_seconds histogram
billing_job_duration_seconds_bucket{worker="billing-worker-02",le="0.5"} 1
billing_job_duration_seconds_bucket{worker="billing-worker-02",le="1"} 1
billing_job_duration_seconds_bucket{worker="billing-worker-02",le="2.5"} 2
billing_job_duration_seconds_bucket{worker="billing-worker-02",le="5"} 2
billing_job_duration_seconds_bucket{worker="billing-worker-02",le="10"} 3
billing_job_duration_seconds_bucket{worker="billing-worker-02",le="+Inf"} 3
billing_job_duration_seconds_count{worker="billing-worker-02"} 3
billing_job_duration_seconds_sum{worker="billing-worker-02"} 10.4
```

## Works With

| Backend                | Status |
| ---------------------- | ------ |
| Prometheus             | ✅      |
| VictoriaMetrics        | ✅      |
| Thanos Receive         | ✅      |
| Grafana Mimir / Cortex | ✅      |

## Why Not `prometheus_client`?

| Requirement                       | prometheus_client | This Client |
| --------------------------------- | :---------------: | :---------: |
| Push without HTTP server          |         ❌         |      ✅      |
| Full control of timestamps        |         ❌         |      ✅      |
| Transparent histogram aggregation |         ❌         |      ✅      |
| Works in cron / short-lived jobs  |         ⚠️         |      ✅      |
