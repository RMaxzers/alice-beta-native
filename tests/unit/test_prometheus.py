"""Prometheus adapter parsing against canned API responses served by the `net` fake receiver (127.0.0.1:9090)."""
from __future__ import annotations

import time

import httpx
import pytest

from services.observability.prometheus import CATALOG, MAX_RANGE_S, MAX_SAMPLES, PrometheusAdapter, PromError, summarize_series

URL = "http://127.0.0.1:9090"


def serve(net, fn):
    net.handlers["127.0.0.1:9090"] = fn


async def test_instant_parsing_and_catalog_query(net):
    now = time.time()
    seen = {}

    def h(req):
        seen.update(req.url.params)
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": [
            {"metric": {"gpu": "0"}, "value": [now - 5, "42.5"]}]}})
    serve(net, h)
    r = await PrometheusAdapter(URL).instant("gpu_util_percent")
    assert seen["query"] == CATALOG["gpu_util_percent"][0]
    assert r["values"][0]["value"] == 42.5 and r["unit"] == "% GPU" and 4 <= r["values"][0]["age_s"] < 60
    assert r["no_data"] is False and r["source"] == "prometheus"


async def test_no_data_is_not_zero(net):
    serve(net, lambda req: httpx.Response(200, json={"status": "success", "data": {"result": []}}))
    r = await PrometheusAdapter(URL).instant("gpu_temp_c")
    assert r["no_data"] is True and r["values"] == []


@pytest.mark.parametrize("resp", [
    httpx.Response(200, json={"status": "error", "errorType": "bad_data", "error": "parse error"}),
    httpx.Response(502, text="<html>Bad Gateway</html>"),
    httpx.Response(200, text="not json"),
])
async def test_errors_become_prom_error(net, resp):
    serve(net, lambda req: resp)
    with pytest.raises(PromError):
        await PrometheusAdapter(URL).instant("host_cpu_percent")


async def test_unreachable_is_prom_error(net):
    net.handlers.pop("127.0.0.1:9090", None)

    def refuse(req):
        raise httpx.ConnectError("refused")
    serve(net, refuse)
    with pytest.raises(PromError, match="no disponible"):
        await PrometheusAdapter(URL).instant("host_cpu_percent")


async def test_range_clamped_bounded_and_gaps_reported(net):
    params = {}
    end = 1_800_000_000.0

    def h(req):
        params.update(req.url.params)
        pts = [[end - 3600 + i * 15, str(i)] for i in range(0, 120)] + [[end - 600 + i * 15, "7"] for i in range(40)]
        return httpx.Response(200, json={"status": "success", "data": {"result": [{"metric": {}, "values": pts}]}})
    serve(net, h)
    r = await PrometheusAdapter(URL).range("gpu_util_percent", end - 10 * MAX_RANGE_S, end)
    assert float(params["start"]) == end - MAX_RANGE_S  # clamped to 24 h
    assert (end - float(params["start"])) / float(params["step"]) <= MAX_SAMPLES
    r = await PrometheusAdapter(URL).range("gpu_util_percent", end - 3600, end, step=15)
    cov = r["coverage"]
    assert 0 < cov["fraction"] < 1 and len(cov["gaps"]) == 1  # 30-min hole in the middle is reported, not interpolated
    s = summarize_series(r)[0]
    assert s["max"] == 119 and s["samples"] == 160


async def test_invalid_interval(net):
    with pytest.raises(PromError):
        await PrometheusAdapter(URL).range("gpu_util_percent", 100, 50)


def test_catalog_only_names_accepted_by_api(api):
    r = api.c.get("/api/observability/range", params={"metric": 'up{job="x"} or vector(1)'})
    assert r.status_code == 422
