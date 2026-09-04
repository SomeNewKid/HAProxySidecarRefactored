"""Shared Docker sandbox network names, addresses, ports, and URLs."""

LOCALHOST = "localhost"
LOOPBACK_IPV4_ADDRESS = "127.0.0.1"
ANY_IPV4_ADDRESS = "0.0.0.0"

DOCKER_HOST_GATEWAY_HOSTNAME = "host.docker.internal"
DOCKER_GATEWAY_HOSTNAME = "gateway.docker.internal"
KUBERNETES_DOCKER_HOSTNAME = "kubernetes.docker.internal"
CLOUD_METADATA_HOSTNAME = "metadata.google.internal"
CLOUD_METADATA_IPV4_ADDRESS = "169.254.169.254"
BLOCKED_HOSTNAME_ADDRESS = ANY_IPV4_ADDRESS

SQUID_GATEWAY_ALIAS = "egress-gateway"
SQUID_GATEWAY_PORT = 3128

MCP_SIDECAR_ALIAS = "mcp-sidecar"
MCP_SIDECAR_PORT = 8000

JINA_READER_ALIAS = "jina-reader"
JINA_READER_PORT = 8081
JINA_READER_READINESS_URL = "https://example.com"

CODE_SIDECAR_ALIAS = "code-sidecar"
CODE_SIDECAR_PORT = 8090

HAPROXY_SIDECAR_ALIAS = "haproxy-sidecar"
MARIADB_DEFAULT_PORT = 3306

OLLAMA_SIDECAR_ALIAS = "ollama-sidecar"
OLLAMA_SIDECAR_PORT = 11434


def http_url(host: str, port: int, path: str = "") -> str:
    """Return a canonical HTTP URL for a sandbox network endpoint."""
    if path and not path.startswith("/"):
        path = f"/{path}"

    return f"http://{host}:{port}{path}"
