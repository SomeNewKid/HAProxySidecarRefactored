# HAProxySidecar

HAProxySidecar is a Python command-line project for running an OpenAI Agents SDK
workload inside a hardened, disposable Docker sandbox with supporting sidecar
containers.

The current focus is a Docker sidecar environment that demonstrates controlled
network egress, MCP tool exposure, HAProxy access to host MariaDB, Jina Reader,
code execution, Ollama, and Playwright screenshot capture while keeping direct
sidecar details out of the AI agent container.

The default topology combines:

- a sandboxed AI agent container
- a Squid proxy sidecar for controlled network egress
- an MCP server sidecar that exposes only declared tools/resources
- an HAProxy sidecar that proxies MariaDB TCP traffic to the host
- Jina Reader, code execution, and Ollama sidecars for the current
  sidecar-availability demonstration
- a Docker internal network that lets containers communicate without exposing
  sidecars directly to the host

> [!WARNING]
> This is an experimental sandboxing and sidecar orchestration project. It is a
> learning and hardening exercise, not a finished security model.

## Current Workload

The sample workload demonstrates a hosted GPT model, MCP tool exposure, HAProxy,
a host MariaDB database, sidecar availability checks, and Playwright screenshot
capture working together.

On each run, the sandbox agent:

1. Calls the MCP sidecar tool `get_active_items`.
2. The MCP sidecar connects to MariaDB through `haproxy-sidecar:3306`.
3. HAProxy proxies that TCP connection to `host.docker.internal:3306`.
4. The MCP tool queries `agent_allowed.items` for records where
   `status = 'active'`.
5. The GPT-backed agent generates a simple HTML document listing those active
   items.
6. The agent saves the document as `/sandbox-output/site/index.html`.
7. Non-agentic Python code injects demonstration sections into the generated
   HTML for Squid Proxy, Code sidecar, Jina Reader, and Ollama sidecar.
8. Playwright serves `/sandbox-output/site` as a static website inside the
   agent container and captures a full-page PNG screenshot at
   `/sandbox-output/site-screenshot.png`.
9. The agent saves and prints a short status message in
   `/sandbox-output/answer.txt`.

The agent uses the OpenAI Agents SDK with the default model configured in
`src/sandbox_agent/openai_agent.py`:

```text
gpt-4.1-mini
```

The model is expected to make its own MCP tool calls for the core active-item
table. The sidecar demonstration sections are injected after the model-generated
HTML is saved so missing sections indicate non-agentic sidecar failures rather
than an LLM choosing not to call a tool.

## Run

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m sandbox_agent
```

The host-side command:

1. Loads `src/sandbox_agent/sandbox_spec.toml`.
2. Validates the requested capabilities and sidecar configuration.
3. Builds or reuses a hash-tagged Docker image for the agent container.
4. Builds or refreshes sidecar images when their declared sidecars need local
   images.
5. Creates a per-run Docker internal network.
6. Starts Squid when `network` is declared.
7. Starts Jina Reader, code execution, HAProxy, and Ollama when their
   capabilities are declared, stopping orchestration if readiness checks fail.
8. Starts the MCP sidecar when declared tools/resources require it, and exposes
   only those declared MCP tools/resources.
9. Runs the disposable agent container.
10. Persists run artifacts and removes disposable containers/network.

Run artifacts are written under:

```text
.docker_sandbox/runs/run-YYYY-mm-dd-HH-MM-SS/
```

## Sandbox Spec

The sandbox is driven by a declarative TOML file:

```toml
schema_version = 1
capabilities = [
  "network",
  "mcp_client",
  "openai_agents",
  "jina_reader",
  "code_execution",
  "haproxy",
  "ollama",
  "playwright_chromium",
]

[squid_proxy]
allowed_domains = [
  ".example.com",
]
allowed_ip_addresses = []

[haproxy]
ports = [
  3306,
]

[ollama_sidecar]
models = [
  "qwen3:4b",
]

[mcp_sidecar]
tools = [
  "get_html_element_name",
  "get_active_items",
  "jina_read_url",
  "run_python_script",
]
resources = []
```

The design rule is that the sandbox starts minimal, and every softened boundary
must be declared. Unknown top-level keys, unknown table keys, and unsupported
capability values fail closed.

### HAProxy Spec

Declaring `"haproxy"` requires:

```toml
[haproxy]
backend_host = "host.docker.internal"
ports = [
  3306,
]
```

Rules:

- `haproxy` requires the `network` capability.
- `[haproxy]` is required when the `haproxy` capability is declared.
- `[haproxy]` is rejected unless the `haproxy` capability is declared.
- `backend_host` is optional and defaults to `host.docker.internal`.
- `ports` must be a non-empty list of unique TCP ports.
- HAProxy listens on each declared port and proxies to the same backend port.
- No HAProxy ports are published to the host.

The default HAProxy sidecar maps:

```text
haproxy-sidecar:3306 -> host.docker.internal:3306
```

The sidecar starts on Docker's `bridge` network so it can reach
`host.docker.internal`, then joins the sandbox internal network with alias
`haproxy-sidecar` so the MCP sidecar can reach it. This is necessary because the
sandbox network is created with `docker network create --internal`.

## Runtime Environment

The default workload needs these host environment variables:

```text
OPENAI_API_KEY=<OpenAI API key>
SANDBOX_TESTER_MARIADB_CREDENTIALS=<username,password>
```

`SANDBOX_TESTER_MARIADB_CREDENTIALS` is passed only to the MCP sidecar when
HAProxy is enabled. It must use a comma-separated value:

```text
sandbox_tester,password_goes_here
```

When HAProxy is enabled, the MCP sidecar receives:

```text
MARIADB_HOST=haproxy-sidecar
MARIADB_PORT=3306
MARIADB_DATABASE=agent_allowed
SANDBOX_TESTER_MARIADB_CREDENTIALS=<from host environment>
```

The AI agent container does not receive `MARIADB_HOST`, `MARIADB_PORT`,
`MARIADB_DATABASE`, or `SANDBOX_TESTER_MARIADB_CREDENTIALS`.

## Capabilities

Supported capabilities include:

- `network`: enables the Squid egress gateway and Docker internal networking.
- `mcp_client`: installs the Python MCP client package in the agent image and
  requires `network`.
- `openai`: installs the OpenAI Python SDK for direct client workloads.
- `openai_agents`: installs the OpenAI Agents SDK and requires `network`.
- `anthropic_claude`: installs the Claude Agent SDK, enables Anthropic API key
  passthrough, allows shell/process spawning, and requires `network`.
- `anthropic_python`: installs the Anthropic Python SDK and requires `network`.
- `ibm_beeai`: installs BeeAI runtime support and requires `network`.
- `google_adk`: installs Google ADK runtime support and requires `network`.
- `langchain`: installs LangChain runtime support and requires `network`.
- `langgraph`: installs LangGraph runtime support and requires `network`.
- `microsoft_agent`: installs Microsoft Agent Framework runtime support and
  requires `network`.
- `crewai`: installs CrewAI runtime support and requires `network`.
- `otto_agent`: installs OpenAI SDK support for Otto Agent workloads and
  requires `network`.
- `haproxy`: starts the HAProxy TCP proxy sidecar and requires `network`.
- `code_execution`: starts the code-execution sidecar for constrained Python
  script execution.
- `jina_reader`: starts the Jina Reader sidecar for readable page/document
  fetching.
- `ollama`: starts the Ollama sidecar and requires `network`.
- `playwright_chromium`: installs Playwright/Chromium runtime support for
  browser automation and screenshot capture.
- `shell_access`: explicitly permits process spawning inside the otherwise
  locked-down agent container.

Provider-backed capabilities can add provider domains and host environment
variables. With the default GPT-backed workload, the agent uses the hosted
OpenAI API and therefore needs `OPENAI_API_KEY`. Declaring `ollama` deploys the
Ollama sidecar and exposes `OLLAMA_BASE_URL`/`OLLAMA_MODEL` to the agent
container, but it does not replace the hosted OpenAI model used by the default
OpenAI Agents SDK workload.

## Sidecars

### HAProxy

The HAProxy sidecar uses:

```text
haproxy:latest
```

For each run, the harness generates a run-local `haproxy.cfg` and mounts it
read-only at:

```text
/usr/local/etc/haproxy/haproxy.cfg
```

For the default spec, the generated config listens on container port `3306` and
forwards TCP traffic to `host.docker.internal:3306`.

HAProxy is intentionally not published to the host. In the current design,
reachability is restricted by:

- only giving the MCP sidecar the MariaDB environment variables
- not giving database environment variables to the AI agent container
- exposing database access only through declared MCP tools
- not publishing HAProxy ports

Later hardening could add source ACLs, iptables, separate Docker networks, or
more granular network segmentation.

### MCP Sidecar

When launched by the Docker harness, the MCP sidecar runs on the internal
network with alias `mcp-sidecar`, and the agent receives:

```text
MCP_SIDECAR_URL=http://mcp-sidecar:8000/mcp
```

The MCP sidecar reads an exposure file generated from `[mcp_sidecar]`. With no
declared tools or resources, it exposes nothing. Unknown exposure names fail
closed at server startup.

Implemented MCP tools include:

- `get_html_element_name`
- `get_active_items`
- `microsoft_docs_search`
- `microsoft_docs_fetch`
- `microsoft_code_sample_search`
- `jina_read_url`
- `run_python_script`

`get_active_items` connects to MariaDB using `pymysql` and runs:

```sql
SELECT id, item_key, title, status, notes, quantity, created_at, updated_at
FROM items
WHERE status = 'active'
ORDER BY id
```

The tool returns JSON text. Tool calls are audited in
`mcp-sidecar-tool-calls.jsonl`; credential values are not written to the audit
record.

Implemented MCP resources include:

- `answer_format`, exposed as
  `mcp-sidecar://instructions/answer-format.md`

### Squid Proxy

The Squid sidecar runs with network alias `egress-gateway` and listens on port
`3128`. Containers that need outbound network access receive:

```text
HTTP_PROXY=http://egress-gateway:3128
HTTPS_PROXY=http://egress-gateway:3128
```

`[squid_proxy]` controls the egress allowlist.

### Code Execution

The optional `code_execution` capability starts a local code-execution sidecar
with alias `code-sidecar`. The AI agent does not call it directly; instead,
`[mcp_sidecar].tools` must expose `run_python_script`, and the MCP sidecar
forwards script requests to:

```text
CODE_SIDECAR_URL=http://code-sidecar:8090
```

### Jina Reader

The optional `jina_reader` capability starts `ghcr.io/jina-ai/reader:oss` with
alias `jina-reader`. The MCP sidecar receives:

```text
JINA_READER_URL=http://jina-reader:8081
```

### Ollama

Ollama support is enabled in the default spec to demonstrate that the sidecar is
available. The default agent workload still uses the hosted OpenAI model for its
main task, then non-agentic Python asks the configured Ollama model for a
child-friendly joke and injects the result into the generated HTML.

Declaring `"ollama"` requires:

```toml
[ollama_sidecar]
models = [
  "model-name:tag",
]
```

The Ollama image hash is separate from the agent image hash. Changing only the
normalized Ollama model list changes only the Ollama sidecar image name. Merely
reordering the same model list does not trigger a different Ollama image name.

Models are pulled during the Ollama image build, not at container runtime.

## Run Artifacts

A successful default run contains files similar to:

```text
.docker_sandbox/runs/run-YYYY-mm-dd-HH-MM-SS/
  Dockerfile
  answer.txt
  config.json
  gateway-logs.json
  gateway-start-results.json
  haproxy.cfg
  code-sidecar-logs.json
  code-sidecar-metadata.json
  code-sidecar-readiness-results.json
  code-sidecar-start-results.json
  haproxy-sidecar-logs.json
  haproxy-sidecar-metadata.json
  haproxy-sidecar-readiness-results.json
  haproxy-sidecar-start-results.json
  haproxy-sidecar-stderr.txt
  haproxy-sidecar-stdout.txt
  jina-reader-logs.json
  jina-reader-metadata.json
  jina-reader-readiness-results.json
  jina-reader-start-results.json
  landlock-policy.json
  mcp-sidecar-exposure.json
  mcp-sidecar-logs.json
  mcp-sidecar-metadata.json
  mcp-sidecar-readiness-results.json
  mcp-sidecar-start-results.json
  mcp-sidecar-stderr.txt
  mcp-sidecar-stdout.txt
  mcp-sidecar-tool-calls.jsonl
  ollama-sidecar-logs.json
  ollama-sidecar-metadata.json
  ollama-sidecar-readiness-results.json
  ollama-sidecar-start-results.json
  resolved-profile.json
  run-metadata.json
  sandbox-spec.json
  seccomp-profile.json
  site-screenshot.png
  site/index.html
  squid.conf
  stderr.txt
  stdout.txt
```

`answer.txt` contains the final status message saved by the agent. `stdout.txt`
contains the same message printed by the in-container process. `site/index.html`
contains the generated and post-processed HTML document. `site-screenshot.png`
contains a full-page screenshot of that static site.

`mcp-sidecar-tool-calls.jsonl` is the MCP audit log. For the default workload,
it should include a successful `get_active_items` call returning the active
MariaDB items as JSON.

## Sandbox Probes

The copied SandboxTester probe suite can be run against the generated sandbox:

```powershell
.\.venv\Scripts\python.exe -m sandbox_agent --test-sandbox
```

To serialize probe evidence for troubleshooting:

```powershell
.\.venv\Scripts\python.exe -m sandbox_agent --test-sandbox --serialize-evidence
```

## Requirements

- Python 3.11.
- PowerShell on Windows.
- Docker Desktop with Linux containers enabled.
- MariaDB running on the host and reachable from Docker as
  `host.docker.internal:3306`.
- A database named `agent_allowed` with an `items` table compatible with the
  default `get_active_items` query.
- A MariaDB user whose credentials are available in
  `SANDBOX_TESTER_MARIADB_CREDENTIALS`.
- `OPENAI_API_KEY` for the default GPT-backed workload.
- Network access during image builds to download Python packages and Docker base
  images.

Docker image builds can take several minutes the first time an image is created.
Sidecar images are inspected or built during startup so dependency and
Dockerfile changes are picked up.

## Setup

Create the virtual environment and install development dependencies:

```powershell
.\scripts\setup-dev.ps1
```

The setup script expects Python 3.11 at the path configured in
`scripts\setup-dev.ps1`.

## Development Checks

Run formatting, linting, type checking, and tests:

```powershell
.\scripts\check.ps1
```

This runs:

- `ruff format .`
- `ruff check .`
- `pyright`
- `pytest`

## Architecture

The project has five main top-level packages:

- `sandbox_agent`: the in-container workload. It owns the OpenAI Agents SDK
  prompt, MCP client calls, HTML document generation, sidecar demonstration
  injection, screenshot capture, and artifact saving.
- `mcp_sidecar`: the MCP server container workload. It owns local MCP resources,
  local MCP tools, Microsoft Learn proxy tools, MariaDB access, Jina Reader
  client logic, code-execution client logic, streamable HTTP server setup, and
  sidecar audit logging.
- `code_sidecar`: the optional no-network code-execution sidecar.
- `docker_sandbox`: the host/container harness. It owns sandbox spec loading,
  Dockerfile generation, image creation, Docker local network creation, sidecar
  startup, readiness checks, disposable agent container execution, artifact
  persistence, and teardown.
- `sandbox_tester`: the copied probe suite used by `--test-sandbox`.

The command path deliberately differs by location:

- On the host, `python -m sandbox_agent` delegates to `docker_sandbox`.
- Inside the container, `python -m sandbox_agent` runs the workload.

The in-container path is guarded by `SANDBOX_AGENT_CONTAINER=1` and expected
mounts such as `/sandbox-output`, `/sandbox-work`, and `/sandbox-source/src`.

The default Docker topology is:

```text
Docker host
  docker_sandbox host runner
    |
    +-- Docker bridge network
    |     |
    |     +-- haproxy-sidecar-* container
    |           backend: host.docker.internal:3306
    |
    +-- Docker internal sandbox network
          |
          +-- sandbox-agent-* container
          |     MCP_SIDECAR_URL=http://mcp-sidecar:8000/mcp
          |     OLLAMA_BASE_URL=http://ollama-sidecar:11434
          |
          +-- mcp-sidecar-* container
          |     network alias: mcp-sidecar
          |     MARIADB_HOST=haproxy-sidecar
          |     JINA_READER_URL=http://jina-reader:8081
          |     CODE_SIDECAR_URL=http://code-sidecar:8090
          |
          +-- haproxy-sidecar-* container
          |     network alias: haproxy-sidecar
          |
          +-- jina-reader-* container
          |     network alias: jina-reader
          |
          +-- code-sidecar-* container
          |     network alias: code-sidecar
          |
          +-- ollama-sidecar-* container
          |     network alias: ollama-sidecar
          |
          +-- squid proxy container
                network alias: egress-gateway
```

The topology is capability-driven. Removing sidecar capabilities from the TOML
omits their corresponding containers and environment wiring.

## Project Structure

```text
ARCHITECTURE.png               Static Docker topology infographic

src/sandbox_agent/
  __main__.py                  Package entry point for python -m sandbox_agent
  cli.py                       Host delegation and in-container workload entry point
  openai_agent.py              OpenAI Agents SDK workload
  openai_tools.py              OpenAI Agents SDK tool adapters
  sandbox_spec.toml            Declarative sandbox capability spec
  tools.py                     Neutral tools, MCP client calls, and artifact saving

src/mcp_sidecar/
  __main__.py                  Package entry point for python -m mcp_sidecar
  audit.py                     JSONL audit logging for resources and tools
  cli.py                       MCP sidecar command-line entry point
  resources.py                 Local MCP resources
  server.py                    FastMCP server construction and exposure registry
  tools.py                     Local, MariaDB, Microsoft Learn, Jina, and code tools
  dockerfile/Dockerfile        MCP sidecar image definition

src/code_sidecar/
  __main__.py                  Package entry point for python -m code_sidecar
  cli.py                       Code sidecar command-line entry point
  runner.py                    Child-process script validator and runner
  server.py                    Internal HTTP service and result capture
  dockerfile/Dockerfile        Code sidecar image definition

src/docker_sandbox/
  __main__.py                  Package entry point for python -m docker_sandbox
  capabilities.py              Shared capability names and capability families
  cli.py                       Docker sandbox command-line orchestration
  container_factory.py         Docker image inspection and build
  container_guard.py           Runtime guard for in-container execution
  landlock_runner.py           Linux Landlock path-policy launcher
  models.py                    Docker orchestration dataclasses
  run_results.py               Local run artifact persistence
  sandbox_container.py         High-level sandbox run coordinator
  sandbox_spec.py              Compatibility facade for sandbox spec APIs
  spec_environment.py          Runtime environment declarations from specs
  spec_models.py               Normalized sandbox spec dataclasses
  spec_sections.py             TOML section readers and normalization
  spec_validation.py           Top-level and cross-capability validation
  agent_container/
    fixtures.py                Run-local filesystem fixture preparation
    hardening.py               Locked-down agent container profile hardening
    image.py                   Agent Dockerfile package selection
    policy_artifacts.py        Landlock and seccomp artifact writing
    run.py                     Agent container Docker run command construction
  dockerfile/remove_python_packaging.py
  dockerfile/runtime_sitecustomize.py
  orchestration/
    artifacts.py               JSON artifact helpers
    docker.py                  Docker command helpers
    environment.py             Run context and container/network names
    network.py                 Shared hostnames, aliases, and ports
    results.py                 DockerRunResult assembly
    run_artifacts.py           Initial run artifact writing
    sidecar_lifecycle.py       Ordered sidecar startup, readiness, logs, cleanup
    types.py                   Neutral orchestration dataclasses
    wiring.py                  Explicit capability-to-sidecar wiring rules
  sidecars/
    code_execution.py          Code sidecar orchestration
    haproxy.py                 HAProxy sidecar orchestration
    jina_reader.py             Jina Reader sidecar orchestration
    mcp.py                     MCP sidecar orchestration
    ollama.py                  Ollama sidecar orchestration
    squid_gateway.py           Squid gateway sidecar orchestration

src/sandbox_tester/
  Probe definitions and report generation used by --test-sandbox

tests/
  Unit and integration-style tests for sandbox specs, sidecars, tools, and
  orchestration helpers

scripts/
  setup-dev.ps1
  check.ps1
```

## Notes

HAProxySidecar is a learning and hardening exercise, not a security proof. The
container policy reduces accidental host exposure and makes required capability
softening visible, but Docker, Landlock, seccomp, Squid, MCP tool boundaries,
sidecar behavior, and Python runtime guards should not be interpreted as a
complete isolation guarantee.

The current "only MCP sidecar can access MariaDB" posture is practical rather
than absolute: the agent is not given database environment variables and the
database tool is only exposed through MCP declarations, but Docker networking is
not yet enforcing per-container ACLs.

Generated content can vary between runs because it is model-generated.

Run artifacts under `.docker_sandbox/runs` are ignored by Git.

## Third-Party Notices

This project uses third-party packages including `mcp`, `openai`,
`openai-agents`, `pillow`, and `pymysql`. It also uses Docker images such as
`python:3.12-slim` for the agent, MCP sidecar, and code sidecar,
`ubuntu/squid:latest` for the Squid gateway, `haproxy:latest` for the HAProxy
sidecar, `ollama/ollama:latest` for Ollama sidecar runs, and
`ghcr.io/jina-ai/reader:oss` for the Jina Reader sidecar. See each package and
image license metadata for details.

## License

GNU General Public License v3.0. See the `LICENSE` file for details.
