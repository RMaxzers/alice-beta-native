"""Alice's own Prometheus metrics, served on a separate loopback port (never behind Tailscale Serve).
Labels are low-cardinality only: never prompts, users, documents, URLs or request IDs.
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server

REGISTRY = CollectorRegistry()
_B = (0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, 120)

REQUESTS = Counter("alice_requests", "User requests (not provider attempts)", ["route", "provider", "model_alias", "status"], registry=REGISTRY)
REQUEST_DURATION = Histogram("alice_request_duration_seconds", "End-to-end request duration", ["route", "provider"], buckets=_B, registry=REGISTRY)
QUEUE_WAIT = Histogram("alice_queue_wait_seconds", "Time waiting for the local generation slot", buckets=_B, registry=REGISTRY)
PROVIDER_DURATION = Histogram("alice_provider_request_duration_seconds", "Provider call duration per attempt", ["provider"], buckets=_B, registry=REGISTRY)
PROVIDER_ATTEMPTS = Counter("alice_provider_attempts", "Provider attempts incl. retries", ["provider", "status"], registry=REGISTRY)
RAG_DURATION = Histogram("alice_rag_retrieval_duration_seconds", "RAG retrieval duration", buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5), registry=REGISTRY)
ROUTING_DURATION = Histogram("alice_routing_duration_seconds", "Routing decision duration", ["decided_by"], buckets=(0.001, 0.01, 0.1, 0.5, 1, 2, 5), registry=REGISTRY)
TOKENS = Counter("alice_provider_tokens", "Tokens by direction", ["provider", "model_alias", "direction"], registry=REGISTRY)
COST = Counter("alice_provider_cost_usd", "Provider-reported cost (accounted amounts only)", ["provider", "model_alias"], registry=REGISTRY)
EGRESS_BLOCKED = Counter("alice_egress_blocked", "Egress attempts blocked by policy", ["reason"], registry=REGISTRY)
QUEUE_DEPTH = Gauge("alice_queue_depth", "Requests waiting for the local generation slot", registry=REGISTRY)
DEP_UP = Gauge("alice_dependency_up", "1 if the dependency's real health check passed", ["dependency"], registry=REGISTRY)
ERRORS = Counter("alice_errors", "Errors by component", ["component"], registry=REGISTRY)

GPU_UTIL = Gauge("alice_gpu_utilization_percent", "GPU utilization (nvidia-smi)", ["gpu"], registry=REGISTRY)
GPU_MEM_USED = Gauge("alice_gpu_memory_used_bytes", "VRAM used (nvidia-smi)", ["gpu"], registry=REGISTRY)
GPU_MEM_TOTAL = Gauge("alice_gpu_memory_total_bytes", "VRAM total (nvidia-smi)", ["gpu"], registry=REGISTRY)
GPU_TEMP = Gauge("alice_gpu_temperature_celsius", "GPU temperature (nvidia-smi)", ["gpu"], registry=REGISTRY)
GPU_POWER = Gauge("alice_gpu_power_watts", "GPU power draw (nvidia-smi)", ["gpu"], registry=REGISTRY)
GPU_SAMPLE_OK = Gauge("alice_gpu_sample_success", "1 if last nvidia-smi sample succeeded", registry=REGISTRY)

OLLAMA_MODELS_INSTALLED = Gauge("alice_ollama_models_installed", "Installed Ollama models", registry=REGISTRY)
OLLAMA_MODEL_LOADED = Gauge("alice_ollama_model_loaded_vram_bytes", "VRAM held by a loaded Ollama model", ["model"], registry=REGISTRY)


def serve(port: int) -> None:
    start_http_server(port, addr="127.0.0.1", registry=REGISTRY)
