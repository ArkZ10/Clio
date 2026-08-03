"""Pure, network-free endpoint classification.

is_local() is ported from Odysseus' src/model_context.py (is_local_endpoint),
extended with a "*.local" mDNS-hostname check. detect_provider() is ported
from src/llm_core.py (_host_match, _is_ollama_native_url, _detect_provider),
collapsed to the three providers llm_switch supports today.
"""
import ipaddress
from urllib.parse import urlparse

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
# Tailscale uses the CGNAT range 100.64.0.0/10, NOT all of 100.0.0.0/8 --
# a bare "100." prefix would misclassify public addresses outside that block.
_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _in_tailscale_range(host: str) -> bool:
    try:
        return ipaddress.ip_address(host) in _TAILSCALE_CGNAT
    except ValueError:
        return False


def _is_private_ip_literal(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in network for network in _PRIVATE_NETWORKS)


def is_local(base_url: str, kind: str = "auto") -> bool:
    """Classify an endpoint as local or not.

    kind="local" -> always True. kind="api" -> always False. kind="auto"
    (default) -> True if the host is loopback / a private IP / a Tailscale
    CGNAT address / a "*.local" mDNS hostname.
    """
    if kind == "local":
        return True
    if kind == "api":
        return False

    try:
        host = (urlparse(base_url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False

    return (
        host in _LOCAL_HOSTS
        or host.endswith(".local")
        or _is_private_ip_literal(host)
        or _in_tailscale_range(host)
    )


def _host_match(url: str, *domains: str) -> bool:
    """True if url's hostname equals any of `domains` or is a subdomain of one."""
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return False
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


def _is_ollama_native_url(url: str) -> bool:
    """True for native Ollama API URLs (port 11434, /api path, or Ollama Cloud)."""
    try:
        parsed = urlparse(url or "")
    except Exception:
        return False
    host = parsed.hostname or ""
    path = (parsed.path or "").rstrip("/")
    if _host_match(url, "ollama.com"):
        return True
    if path.startswith("/v1"):
        return False
    local_ollama_host = host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or parsed.port == 11434
    return local_ollama_host and (path == "" or path == "/api" or path.startswith("/api/"))


def detect_provider(base_url: str) -> str:
    """Detect the API provider from a base URL: "anthropic" | "ollama" | "openai".

    Unknown hosts (including all other OpenAI-compatible servers -- DeepSeek,
    vLLM, LM Studio, llama.cpp) fall back to "openai".
    """
    if _is_ollama_native_url(base_url):
        return "ollama"
    if _host_match(base_url, "anthropic.com"):
        return "anthropic"
    return "openai"
