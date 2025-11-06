# tests/test_remote_write_client.py
import time
import snappy
import pytest
import requests

import prometheus_remote_write_client as rwc

def decode_wr_from_snappy(data):
    """Decompress snappy payload and parse WriteRequest using the same dynamic schema."""
    Label, Sample, TimeSeries, WriteRequest = rwc._init_schema()
    wr = WriteRequest()
    wr.ParseFromString(snappy.decompress(data))
    return wr


@pytest.fixture
def capture_posts(monkeypatch):
    """
    Monkeypatch requests.Session.post to capture payloads and headers without real HTTP.
    Returns a list of captured call dicts.
    """
    calls = []

    def fake_post(self, url, data=None, headers=None, timeout=None, **kwargs):
        calls.append(
            {
                "url": url,
                "data": data,
                "headers": headers or {},
                "timeout": timeout,
            }
        )

        class R:
            status_code = 200

            def raise_for_status(self):
                return None

        return R()

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=True)
    return calls


def get_metric_and_labels(ts):
    """Extract metric name (__name__) and label dict from a TimeSeries."""
    metric = None
    labels = {}
    for lable in ts.labels:
        if lable.name == "__name__":
            metric = lable.value
        else:
            labels[lable.name] = lable.value
    return metric, labels


def test_gauge_send_timeseries_basic(capture_posts):
    cli = rwc.RemoteWriteClient("http://example/write", debug=False)
    ts_sec = 1_710_000_000  # seconds
    cli.gauge_set("my_metric", 12.0, labels={"a": "b"}, ts=ts_sec)

    assert len(capture_posts) == 1
    call = capture_posts[0]
    wr = decode_wr_from_snappy(call["data"])
    assert len(wr.timeseries) == 1

    ts = wr.timeseries[0]
    metric, labels = get_metric_and_labels(ts)
    assert metric == "my_metric"
    assert labels == {"a": "b"}
    assert len(ts.samples) == 1
    sm = ts.samples[0]
    assert sm.value == pytest.approx(12.0)
    assert sm.timestamp == ts_sec * 1000  # normalized to ms

    # headers
    assert call["headers"]["Content-Type"] == "application/x-protobuf"
    assert call["headers"]["Content-Encoding"] == "snappy"
    assert call["headers"]["X-Prometheus-Remote-Write-Version"] == "0.1.0"


def test_counter_inc_monotonicity(capture_posts):
    cli = rwc.RemoteWriteClient("http://example/write", debug=False)
    cli.counter_inc("orders", 2, labels={"shop": "a"})
    cli.counter_inc("orders", 3, labels={"shop": "a"})  # cumulative -> 5

    assert len(capture_posts) == 2

    wr_last = decode_wr_from_snappy(capture_posts[-1]["data"])
    ts = wr_last.timeseries[0]
    metric, labels = get_metric_and_labels(ts)
    assert metric == "orders_total"  # name transformed
    assert labels == {"shop": "a"}

    assert len(ts.samples) == 1
    sm = ts.samples[0]
    assert sm.value == pytest.approx(5.0)  # monotonic accumulation


def test_histogram_flush_cumulative_buckets_and_sum_count(capture_posts):
    cli = rwc.RemoteWriteClient("http://example/write", debug=False)
    base = "job_duration_seconds"
    labels = {"w": "x"}
    bounds = [0.5, 1, 2.5, 5, 10]

    # increasing timestamps (ms)
    now = int(time.time() * 1000)
    t1, t2, t3 = now - 120000, now - 60000, now

    cli.histogram_queue(base, 0.6, labels=labels, ts=t1)   # -> <=1
    cli.histogram_queue(base, 2.2, labels=labels, ts=t2)   # -> <=2.5
    cli.histogram_queue(base, 10.0, labels=labels, ts=t3)  # -> <=10

    cli.histogram_flush(base, labels=labels, bounds=bounds)

    # 5 finite buckets + +Inf + _sum + _count = 8 series
    wr = decode_wr_from_snappy(capture_posts[-1]["data"])
    assert len(wr.timeseries) == len(bounds) + 1 + 2

    # final expected cumulative counts after 3 observations
    expected_last = {
        "0.5": 0,
        "1": 1,
        "2.5": 2,
        "5": 2,
        "10": 3,
        "+Inf": 3,
    }
    expected_sum = 0.6 + 2.2 + 10.0  # 12.8
    expected_count = 3

    # Collect by metric and 'le'
    by_bucket_le = {}
    last_sum = None
    last_count = None

    # All samples should have timestamps [t1, t2, t3]
    expected_ts = [t1, t2, t3]

    for ts in wr.timeseries:
        metric, ls = get_metric_and_labels(ts)
        samples = ts.samples
        # Ensure 3 snapshots
        assert [s.timestamp for s in samples] == expected_ts

        if metric.endswith("_bucket"):
            le = ls["le"]
            # last value per bucket
            by_bucket_le[le] = samples[-1].value
        elif metric.endswith("_sum"):
            last_sum = samples[-1].value
        elif metric.endswith("_count"):
            last_count = samples[-1].value

    # Buckets
    for le, v in expected_last.items():
        assert by_bucket_le[le] == pytest.approx(float(v))

    # Sum & Count
    assert last_sum == pytest.approx(expected_sum)
    assert last_count == pytest.approx(float(expected_count))


def test_ts_normalization_seconds_and_millis(capture_posts):
    cli = rwc.RemoteWriteClient("http://example/write", debug=False)

    # seconds input
    cli.send_timeseries("sec_metric", 1, ts=123)
    wr1 = decode_wr_from_snappy(capture_posts[-1]["data"])
    assert wr1.timeseries[0].samples[0].timestamp == 123000

    # milliseconds input
    cli.send_timeseries("ms_metric", 1, ts=1234567890123)
    wr2 = decode_wr_from_snappy(capture_posts[-1]["data"])
    assert wr2.timeseries[0].samples[0].timestamp == 1234567890123


def test_cumulate_helper():
    # mirrors the evolution [0,1,1,0,1,0] (finite buckets + +Inf position) after 3 obs
    non_cum_bks = [0, 1, 1, 0, 1, 0]
    # n = len(bounds) = 5, function appends +Inf separately
    out = rwc.RemoteWriteClient._cumulate(non_cum_bks, 5)
    # cumulative finite buckets: [0,1,2,2,3], +Inf == total count (=3)
    assert out == [0, 1, 2, 2, 3, 3]