# Trustvian + LangGraph — Quick Start (step by step)

Goal: run a small LangGraph agent under `trustvian dev` **without changing the
agent's code**, watch the live behavior graph, then give the agent a new tool
and watch Trustvian report the behavioral change and fail the gate.

Same scenario as the CrewAI and vLLM quick starts (support triage, fake CRM,
the candidate gains `export_customer`); what changes is that the agent is an
explicit LangGraph graph, and that LangGraph's own graph and node spans show
up beside the tools and the model.

Time: about 15 minutes for the first run (model download excluded).

## 0. Prerequisites

| What | How |
|---|---|
| Ollama + a model | `ollama pull qwen2.5:3b` (1.9 GB). The model must support tool calling (`ollama show <model>` lists `tools`); gemma3 does not. To use vLLM or OpenAI instead, see [Other model servers](#other-model-servers). |
| Python 3.11+ | `python3 --version` |
| Trustvian v0.11.0 | **(a)** release archive: download the v0.11.0 macOS/Linux archive from the [release page](https://github.com/trustvian/trustvian/releases/tag/v0.11.0), extract it, add the directory to `PATH` — `trustvian`, `trustvian-local` and `trustvian-collector` ship side by side. **(b)** from a checkout: `git clone --branch v0.11.0 https://github.com/trustvian/trustvian && cd trustvian && make build dev-binaries && export PATH="$PWD/bin:$PATH"` |
| Check | `trustvian version` prints `v0.11.0`; `trustvian dev --help` must work. |

`dev` does not run on Windows; use WSL2.

## 1. Project files

The files in this folder:

```text
requirements.txt     LangGraph + the Ollama and OpenAI chat models + OpenInference + OTel SDK
mock_services.py     fake CRM on 127.0.0.1:8081 (standard library, no dependencies)
tools.py             the agent's tools — imports NEITHER OTel NOR Trustvian
graph.py             the agent as a StateGraph — imports NEITHER OTel NOR Trustvian
run.py               instrumentation harness; runs graph.py unchanged
scenario.yaml        steps 3–5 as one repeatable scenario (step 6)
tests/               the span checks; no model needed
```

`graph.py` and `tools.py` are your application; neither knows OpenTelemetry
exists. `run.py` stands in for a framework's own instrumentation: it builds
the SDK from the environment variables `trustvian dev` hands the child
process, turns on the LangChain + requests instrumentors, and then runs
`graph.py` as-is.

The graph is spelled out rather than taken from a prebuilt agent:

```text
START ──> agent ──tools_condition──> tools ──> agent ...
                └──(no tool call)──> END
```

`agent` is the chat model with the tools bound, `tools` is LangGraph's
`ToolNode`, and `tools_condition` routes to `tools` while the model asks for a
tool and to the end once it answers.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Start the fake CRM (Terminal A)

```bash
python mock_services.py
# listening on http://127.0.0.1:8081
```

## 3. Reference run (Terminal B)

```bash
export LANGSMITH_TRACING=false                 # LangChain's own tracer, off; see below
unset LANGCHAIN_TRACING_V2
export OPENINFERENCE_HIDE_INPUTS=true          # keep prompt/output content out of spans
export OPENINFERENCE_HIDE_OUTPUTS=true
export OPENINFERENCE_HIDE_INPUT_MESSAGES=true  # and every chat message
export OPENINFERENCE_HIDE_OUTPUT_MESSAGES=true

trustvian dev --instrumentation existing \
  --agent support-graph --candidate ref \
  -- python run.py
```

LangChain ships a tracer of its own that, once enabled, sends every prompt,
completion and tool argument to a hosted trace backend. That is a second copy
of exactly the content the four `OPENINFERENCE_HIDE_*` variables keep out of
Trustvian, so it is switched off explicitly rather than left to whatever the
shell happens to export. Do **not** use `OTEL_SDK_DISABLED` for this; `dev`
refuses it.

The banner shows `Run dev-ref-...` (note the run id), `State
~/.trustvian/dev/<hash>` and `Web http://127.0.0.1:<port>/`. Open the web
address: the live view draws the `support-graph` actor and an edge per
behavior, labelled with its category and name. You should see these nine,
written here the way `trustvian eval run` prints them in step 6:

```text
tool/lookup_customer
tool/send_reply
external/qwen2.5:3b → ollama
http/GET → 127.0.0.1           the request lookup_customer makes
http/POST → 127.0.0.1          the request send_reply makes
rpc/LangGraph
rpc/agent
rpc/tools
rpc/tools_condition
```

The four `rpc/…` rows are LangGraph itself — the graph, its two nodes and the
routing function — whose OpenInference spans name no operation (CHAIN, and
AGENT without an agent name for the `agent` node), so Trustvian reads them at
transport fidelity, where a span with no HTTP or database attributes counts as
an `rpc` call named after the span.

All of them are NEW on the first run. When the agent finishes, dev prints
"Run ... complete".

## 4. Candidate run: add a tool to the agent

`GRAPH_VARIANT=candidate` binds a third tool (`export_customer`) and the task
text nudges the agent to use it. No code change, only an environment variable;
in real life this would be a pull request.

```bash
GRAPH_VARIANT=candidate \
trustvian dev --instrumentation existing \
  --agent support-graph --candidate cand \
  -- python run.py
```

Note the run id (`dev-cand-...`).

## 5. Compare

`dev` stops its control plane when the run ends, so start one on the same
state for the comparison (Terminal C). The path is the `State` line of either
banner:

```bash
trustvian-local --state-dir ~/.trustvian/dev/<hash>
```

Then, in Terminal B — in this folder, where `trustvian` finds that control
plane by itself:

```bash
trustvian eval compare \
  --reference-run dev-ref-<...> --candidate-run dev-cand-<...> \
  --max-added-behaviors 0 --max-block-decisions 0 --max-critical-risk-observations 0
echo "exit: $?"
```

Expected:

```text
Behaviors: +1 / -0 / 9 shared
...
  FAIL Added behaviors: 1 (maximum 0)
...
Gate: FAIL
exit: 1
```

The added behavior is the `export_customer` tool; `--json` lists it under
`behavior_diff`. Run the same command with `--max-added-behaviors 1` and it
passes. The Compare tab in the WebUI of Terminal C's control plane shows the
same result; clicking a finding jumps to the observations that are its
evidence.

While Terminal C runs, `trustvian dev` refuses to start a second control plane
on the same state (`a local control plane is already serving this state
directory`). Stop it with Ctrl-C before the next `dev` run, or keep it and add
the `--api-url` that message names.

## 6. Repeat it as a scenario

One run of a model-driven agent is not evidence: the same agent can call a
tool in one run and skip it in the next. `scenario.yaml` runs each side three
times and gates on how many runs a behavior appeared in — a behavior is
*added* when it is in at least one candidate run and in no reference run, and
step 5's limits apply to that count:

```bash
trustvian eval run --scenario scenario.yaml
echo "exit: $?"
```

It needs the control plane from Terminal C, and Terminal B's exports. Expected:

```text
Behavior                                  reference   candidate
  ...
  tool/export_customer                           0/3         3/3   + added
  ...
  FAIL repeatedly added behaviors: 1 (<= 0)
...
Gate: FAIL
exit: 1
```

The six repetitions are ordinary `trustvian dev` runs, each with a learning
scope of its own; the scenarios page of the WebUI lists the execution.
`--json` writes the result document. Before you trust a gate like this on a
model-driven agent, measure how often the unchanged agent fails against
itself: Trustvian's `docs/platform-cli.md` ("Calibrating `N`, `k` and `j`")
has the procedure.

## 7. What is different from the CrewAI quick start

- **The graph is explicit.** `graph.py` builds a `StateGraph` with an `agent`
  node, a `ToolNode` and a `tools_condition` edge, instead of a crew of
  agents and tasks. A model that keeps calling tools is stopped after 17
  steps (eight tool rounds and an answer), the crew's `max_iter=8`.
- **One instrumentor sees everything.** LangGraph runs on LangChain's
  callbacks, so OpenInference's LangChain instrumentor records the graph, the
  nodes, every model call (LLM spans with `llm.model_name`) and every tool
  call (TOOL spans with `tool.name`). No OpenAI or LiteLLM instrumentor is
  needed.
- **The graph shows up as behaviors of its own** — the `rpc/…` rows in step
  3, explained there. They are the same in both runs, so they never become
  an added behavior.
- **The model is chosen in `graph.py`.** `LLM_MODEL` is a plain model name
  (`qwen2.5:3b`, not `ollama/qwen2.5:3b`); `LLM_BASE_URL` switches from
  `ChatOllama` to `ChatOpenAI`. See below.
- **Content stays out by configuration, and a test proves it.** The four
  `OPENINFERENCE_HIDE_*` variables drop chat messages from spans and replace
  `input.value` / `output.value` with OpenInference's fixed `__REDACTED__`
  marker. `tests/test_spans.py` plants marker strings in a ticket, a reply and
  the model's answer and asserts that none of them reaches any span.
- **The control plane outlives the run in step 5** (Terminal C), because a
  comparison needs one.

## Other model servers

`graph.py` uses `ChatOllama` by default, against `OLLAMA_HOST`
(`http://127.0.0.1:11434` when unset). Set `LLM_BASE_URL` and it uses
`ChatOpenAI` against that OpenAI-compatible endpoint instead, with `LLM_MODEL`
as the model name and the key from `OPENAI_API_KEY` — read from the
environment only:

```bash
# vLLM (started with --enable-auto-tool-choice and a --tool-call-parser)
export LLM_BASE_URL=http://<gpu-host>:8000/v1
export LLM_MODEL=<served-model-name>
export OPENAI_API_KEY=EMPTY                  # vLLM ignores it; the client wants one

# OpenAI
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o-mini
export OPENAI_API_KEY=...

# Ollama's own OpenAI-compatible endpoint
export LLM_BASE_URL=http://127.0.0.1:11434/v1
export LLM_MODEL=qwen2.5:3b
export OPENAI_API_KEY=EMPTY
```

Then steps 3–6 exactly as written. The model's row reads
`external/<model> → openai` with `ChatOpenAI`, whichever server answers:
the target is the client's provider, not the server's.

## The tests

```bash
pip install -r requirements-dev.txt
pytest
```

They need no model, no Trustvian and no network beyond loopback: a scripted
chat model returns `AIMessage`s with `tool_calls`, the graph executes them
against the fake CRM, and the spans go to an in-memory exporter set up by
`run.py`'s own `instrument()`. They assert one TOOL span with `tool.name` per
tool call and one LLM span per model call; an `export_customer` span for the
candidate and none for the reference; and that no span carries a chat
message, any content in `input.value` / `output.value`, or the ticket text,
the reply text, the answer or the customer record. The one tool argument that
does reach a span is the customer id, in the URL of the HTTP request
`lookup_customer` makes. The hide settings the tests use are read from
`compose.yaml`, so the tests and the stack cannot disagree.

## Running it with Docker Compose

The same steps with nothing installed on the laptop but Docker and a model
server. Trustvian is built from source inside the image, so no release
archive or Go toolchain is needed either.

| Service | What it is |
|---|---|
| `control-plane` | `trustvian-local` with its SQLite database in a named volume; WebUI and API on `http://127.0.0.1:8080/` |
| `crm` | `mock_services.py` |
| `agent` | one-shot container: `trustvian dev --api-url http://control-plane:8080 … -- python run.py`. Used with `docker compose run`, never started by `up` |
| `ollama` | the model server, CPU inference, models in the `ollama-models` volume |
| `ollama-pull` | one-shot: pulls `LLM_MODEL` into `ollama` on `up`, then exits. The agent waits for it to finish |

Why one long-lived control plane instead of letting `dev` start its own: `dev`
starts a private runtime per invocation and stops it when the run ends. Two
runs that need comparing must share one database, and the browser needs the
server to outlive the run that produced it — so the stack runs one control
plane and every run attaches with `--api-url`, the shape Trustvian's
`docs/local-development.md` calls "running the parts separately" and the one CI
uses.

Files: `compose.yaml`, `Dockerfile` (Trustvian build, release collector image,
control plane, agent runner), `compose/control-plane.sh`, `compose/agent-entrypoint.sh`,
`.env.example`.

### 1. Build and start

```bash
cp .env.example .env              # optional; every value has a default
docker compose --profile agent build  # the control-plane and agent images
docker compose up -d
```

`--profile agent` matters: the agent is not started by `up`, so a plain
`docker compose up --build` never rebuilds it and a changed
`requirements.txt` would not reach the image.

The first build clones Trustvian (`TRUSTVIAN_REF`, default `v0.11.0`) and
compiles `trustvian` and `trustvian-local`; `trustvian-collector` is copied
out of the signed release image
`ghcr.io/trustvian/trustvian-collector:v0.11.0`, pinned by digest
(`TRUSTVIAN_COLLECTOR_IMAGE`). Then it installs LangGraph — a few minutes. To
move to another release, change both values in `.env` together. The first `up` also pulls the model
(`qwen2.5:3b`, 1.9 GB) into the `ollama` service; `docker compose logs -f
ollama-pull` shows when it is ready. Afterwards `http://127.0.0.1:8080/` is
the WebUI, published on the host's loopback only (the runtime is
unauthenticated).

### 2. The model

- **Ollama inside Compose (default).** Nothing to do: `ollama-pull` pulled
  `LLM_MODEL` on `up`. To change the model, set `LLM_MODEL=<model>` in `.env`
  and run `docker compose up -d` again. It must support tool calling:
  `docker compose exec ollama ollama show <model>` lists `tools`. gemma3
  does not — Ollama answers `400 does not support tools`.
- **Ollama on the host.** Faster on a Mac (Metal; Docker is CPU-only there).
  Set `OLLAMA_URL=http://host.docker.internal:11434` in `.env`, keep the
  Ollama app running and `ollama pull` the model on the host; `ollama-pull`
  then skips. On Linux, Ollama must listen on all interfaces:
  `OLLAMA_HOST=0.0.0.0 ollama serve`. (`.env` says `OLLAMA_URL`, not
  `OLLAMA_HOST`, so an `OLLAMA_HOST` exported in your shell for the host's
  Ollama cannot redirect the agent.)
- **vLLM or OpenAI.** Set `LLM_BASE_URL`, `LLM_MODEL` and `OPENAI_API_KEY`
  in `.env` as in [Other model servers](#other-model-servers);
  `ollama-pull` then skips.

A 3B model on CPU is slow and sometimes repeats its tool calls; the behavior
set is still right. `qwen2.5:7b` follows the prompt better if Docker has the
memory for it.

### 3–5. Reference, candidate, compare

```bash
docker compose run --rm agent reference    # prints "run id ref-<timestamp>"
docker compose run --rm agent candidate    # prints "run id cand-<timestamp>"
docker compose run --rm agent compare      # gates the last two; exit 1 = FAIL
echo "exit: $?"
```

`compare` takes two explicit ids too: `docker compose run --rm agent compare
ref-… cand-…`. The gate limits come from `MAX_ADDED_BEHAVIORS`,
`MAX_BLOCK_DECISIONS`, `MAX_CRITICAL_RISK_OBSERVATIONS` (all default 0), passed
with `-e`: `docker compose run --rm -e MAX_ADDED_BEHAVIORS=1 agent compare`.
Expected result is the same as in the native flow: `Behaviors: +1 / …`,
`FAIL Added behaviors: 1 (maximum 0)`, `Gate: FAIL`, exit 1, with
`export_customer` as the added behavior; the Compare tab in the WebUI shows it.

Three things read differently from the native flow:

- `dev`'s banner prints `Web http://control-plane:8080/` — that is the name
  inside the Compose network. On the host, open `http://127.0.0.1:8080/`.
- Run ids are `ref-<utc time>` / `cand-<utc time>`, chosen by the entrypoint
  so `compare` can find the last pair without parsing `dev`'s output.
- The CRM is the `crm` service, so the HTTP rows read `http/GET → crm` and
  `http/POST → crm` instead of `→ 127.0.0.1`.

### 6. The scenario

```bash
docker compose run --rm agent trustvian eval run --scenario scenario.yaml
echo "exit: $?"
```

The same scenario file, against the stack's control plane: `scenario.yaml`
names the project, the agent and both candidates, so it needs no git
checkout in the container. Expected: `tool/export_customer 0/3 3/3 + added`,
`Gate: FAIL`, exit 1.

### Other commands

```bash
docker compose run --rm agent trustvian eval get --id ref-…   # any CLI command, --api-url pre-set
docker compose run --rm agent shell                           # bash in the agent container
docker compose run --rm agent python graph.py                 # the graph without tracing
docker compose logs control-plane                             # the runtime's log
docker compose down                                           # stop; runs and baselines are kept
docker compose down -v                                        # stop and discard all state
```

Editing `graph.py` or `tools.py` needs no rebuild (the directory is
bind-mounted); changing `requirements.txt` does: `docker compose build agent`
(naming the service enables its profile).

### Compose troubleshooting

| Symptom | Cause / fix |
|---|---|
| `the control plane did not answer at http://control-plane:8080` | `docker compose ps` — is `control-plane` healthy? `docker compose logs control-plane` has the reason |
| `httpx.ConnectError` / `Connection refused` from the model | The model server is not reachable from the agent. Default stack: `docker compose ps ollama` and `docker compose logs ollama-pull`. Host Ollama: is the app running, and is `OLLAMA_URL` set? On Linux, `OLLAMA_HOST=0.0.0.0` |
| `does not support tools` | The model has no tool calling (gemma3). Pick one whose `ollama show` lists `tools` |
| WebUI shows the project but no behaviors | The run failed before the first model answer — `docker compose run --rm agent trustvian eval get --id <run id>` shows `failed`; fix the model, run again |
| Build fails while fetching Go modules or cloning | Network/proxy on the build host; `TRUSTVIAN_REF` must be a branch, tag or full SHA that exists |
| Build fails pulling `ghcr.io/trustvian/trustvian-collector` | Registry unreachable, or `TRUSTVIAN_COLLECTOR_IMAGE` names a digest that does not exist; `docker pull` it by hand to see the error |
| `compare` says no run recorded | Run `reference` and `candidate` first, or pass the two ids explicitly |
| Everything reports NEW on every run | You ran `docker compose down -v` in between; the volumes hold the baseline and the runs |

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| dev says "cannot establish instrumentation ownership" | `--instrumentation existing` is missing |
| dev says "cannot determine which agent" | `--agent support-graph` is missing, or `OTEL_SERVICE_NAME` is unset |
| dev says "a local control plane is already serving this state directory" | Terminal C from step 5 is still running; stop it, or pass the `--api-url` the message names |
| `eval compare` / `eval run` says "no local runtime was found" | Start Terminal C (step 5), and run the command from this folder |
| Live view is empty | Does `run.py` print "exporter → http://127.0.0.1:.../v1/traces" at startup? If not, `opentelemetry-exporter-otlp-proto-http` is not installed in the venv |
| No `tool/` rows, only HTTP | `openinference-instrumentation-langchain` is not installed or too old; check with `pip show` |
| dev stops because of `OTEL_SDK_DISABLED=true` | Unset it. To silence LangChain's own tracer use `LANGSMITH_TRACING=false`, not that variable |
| `=== c-1001: stopped after 17 steps ===` | The model kept calling tools; the run still completes and its behaviors are recorded. Try a larger model via `LLM_MODEL` |
| `openai.OpenAIError: Missing credentials` | `LLM_BASE_URL` is set, so `ChatOpenAI` is used; export `OPENAI_API_KEY` (`EMPTY` for vLLM or Ollama) |
| Tool calls show up but all go to one host | Expected: the behavior is `tool/<name>`, read from the tool name; the HTTP request beneath it is a behavior of its own |
