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
| Trustvian v0.12.0 | **(a)** release archive: download the v0.12.0 macOS/Linux archive from the [release page](https://github.com/trustvian/trustvian/releases/tag/v0.12.0), extract it, add the directory to `PATH` — `trustvian`, `trustvian-local` and `trustvian-collector` ship side by side. **(b)** from a checkout: `git clone --branch v0.12.0 https://github.com/trustvian/trustvian && cd trustvian && make build dev-binaries && export PATH="$PWD/bin:$PATH"` |
| Check | `trustvian version` prints `v0.12.0`; `trustvian dev --help` must work. |

`dev` does not run on Windows; use WSL2.

### Upgrading from Trustvian v0.11.0

**The platform database moves one way.** The first v0.12.0 `trustvian-local`
to open a v0.11.0 state migrates it from schema 10 to 15, and v0.11.0 then
refuses it:

```text
trustvian-local: opening platform database: platform: unsupported persistence schema: database reports version 15, this build supports 10
```

This project's state is `dev`'s directory, `~/.trustvian/dev/<hash>/` (the
`State` line of the banner), live mode's `~/.trustvian/live/`, and under
Compose the `trustvian-state` volume. Runs recorded before the upgrade are
kept (a Compose volume from v0.11.0 still listed its runs after the first
v0.12.0 start); what v0.12.0 adds to a record (frequency, fidelity, the
recorded gate, provenance) reads *not recorded* for them. If the
state matters, copy the stopped directory first; to start fresh instead,
remove it (`rm -rf ~/.trustvian/dev/<hash>`). Under Compose, back the volume
up with the stack stopped,

```bash
docker run --rm -v trustvian-langgraph-quickstart_trustvian-state:/state -v "$PWD":/backup \
  alpine tar czf /backup/trustvian-state.tgz -C /state .
```

or start fresh with `docker compose down -v`. Rebuild every image, the live
service's included: it is an image of its own, and `up` reuses an old one.

```bash
docker compose --profile agent --profile live build
```

**Upgrade the control plane before the CLI.** A v0.12.0 `trustvian eval run`
sends fields an older control plane refuses, before any repetition starts:

```text
trustvian: invalid_request: request body is not valid JSON for this endpoint
```

`trustvian dev` starts a control plane of its own from the same directory, so
only one started separately needs checking: Terminal C in step 5, live mode's
in step 8, or any `TRUSTVIAN_API_URL`. `trustvian status` reads a route that
v0.12.0 added; an older control plane answers it with `404`:

```bash
trustvian status --api-url http://127.0.0.1:8080 >/dev/null && echo "v0.12.0 or later"
# against v0.11.0: trustvian: server returned HTTP 404   (exit 3)
```

## 1. Project files

The files in this folder:

```text
requirements.txt     LangGraph + the Ollama and OpenAI chat models + OpenInference + OTel SDK
mock_services.py     fake CRM on 127.0.0.1:8081 (standard library, no dependencies)
tools.py             the agent's tools — imports NEITHER OTel NOR Trustvian
graph.py             the agent as a StateGraph — imports NEITHER OTel NOR Trustvian
run.py               instrumentation harness; runs graph.py unchanged
live.py              live mode (step 8): one trustvian dev per agent, supervised
roles.py             live mode's roles, tickets and per-worker loop
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
export LLM_MODEL=qwen2.5:3b                    # graph.py's model; step 6 records it

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
passes. In the WebUI of Terminal C's control plane, Compare is now part of
**Change Impact**: below the scenario reports, mark one run **Reference** and
the other **Candidate**, then **Compare runs** (Trustvian's `docs/webui.md`,
"Comparing two runs").

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

It needs the control plane from Terminal C, and Terminal B's exports. Three
runs a side took 50 s here. Expected:

```text
support-graph-export   runs 3   (execution scn-support-graph-export-20261013T173244-0c15d5f1)
Recorded
  reference: scenario sha256:afdaf6a0…   inputs not_declared   model qwen2.5:3b   prompt_ref not_recorded
  candidate: scenario sha256:afdaf6a0…   inputs not_declared   model qwen2.5:3b   prompt_ref not_recorded

Behavior                                  reference   candidate
  external/qwen2.5:3b → ollama                   3/3         3/3
  …
  tool/export_customer                           0/3         3/3   + added
  rpc/agent                                      3/3         3/3

Gate (k = 1, j = 0)
  …
  FAIL repeatedly added behaviors: 1 (<= 0)
  …
  PASS min candidate frequency: 3 (>= 3)
  PASS max lost behaviors: 0 (<= 0)
  PASS max llm calls per run: 5 (<= 18)

Sameness
  same_scenario    true
  same_inputs      true
  same_model       true
  same_prompt_ref  not_recorded
  …
Gate: FAIL
exit: 1
```

What the scenario adds to step 5:

- **The model is recorded.** Each side declares `model_env: LLM_MODEL`, the
  variable `graph.py` reads, so the result says which model each side ran
  and whether they were the same (`same_model`). Unset, it declares nothing
  and reads `not_recorded`; that is why step 3 exports it. The prompt
  reference is not declared, so `same_prompt_ref` is `not_recorded`.
- **Three frequency limits**, each at a value the unchanged graph passes:
  run against itself three times (`GRAPH_VARIANT=reference` on both sides),
  it lost no behavior and kept every reference behavior in 3 of 3 candidate
  runs, so `min_candidate_frequency: 3` and `max_lost_behaviors: 0`.
  `max_llm_calls_per_run: 18` is the graph's own ceiling (two tickets of at
  most nine model calls); the runs made 4 to 8. `scenario.yaml` says why
  each value, and why there is no `max_calls_per_run`.

The six repetitions are ordinary `trustvian dev` runs, each with a learning
scope of its own. Before you trust a gate like this on a model-driven agent,
measure how often the unchanged agent fails against itself: Trustvian's
`docs/platform-cli.md` ("Calibrating `N`, `k` and `j`") has the procedure.

### Read it as a report

Every completed execution keeps a report: the sameness, every behavior and
target, tokens, the gate as it was recorded, and suggestions. Read it with
the execution id `eval run` printed on its first line:

```bash
trustvian eval report scn-support-graph-export-20261013T173244-0c15d5f1 --json
trustvian eval report scn-support-graph-export-20261013T173244-0c15d5f1 --format md
```

`--json` (and the default) is Trustvian's result document version 2, the
same document `eval run --json` prints. In it, `comparison.counts` totals
the behavior rows by classification:

```json
"counts": {"rows": "10", "added": "1", "removed": "0", "neither": "9", "not_recorded": "0", "lost": "0"}
```

and each behavior row carries the strings the tables show:

```json
"display": {
  "reference_presence": "0/3",
  "candidate_presence": "3/3",
  "reference_calls_per_run": "0–0",
  "candidate_calls_per_run": "2–3",
  …
}
```

`--format md` renders the same document as Markdown, one table per section,
the Markdown Trustvian's CI renderer produces:

```text
### Trustvian behavioral gate — FAIL
…
| `service` · `tool` · `export_customer` · `local` | `e7528b283e002e05` | 0/3 | 3/3 | 0–0, mean 0 | 2–3, mean 2.333 | **+ added** | no | — | semantic · semantic 7 · transport 0 · unrecorded 0 |
…
| minimum candidate presence of reference behaviors | 3 | at least | 3 | pass | |
| lost behaviors | 0 | at most | 0 | pass | |
| calls per run | | | | not configured | |
| model calls per run | 5 | at most | 18 | pass | |
…
- `compare.added_in_all_runs`: `tool/export_customer was added in 3/3 candidate runs. If this was expected, add it to the scenario; otherwise investigate before promoting.`
```

**There is no cost.** The tokens are counted, and the cost section says why
there is no figure:

```text
| Input tokens | 9122 | 5978 | -3144 |
…
Cost: not available — no pricing table is configured (`pricing_not_configured`).
```

Trustvian ships no prices, and neither does this project. If you have real
ones, `trustvian-local --pricing <file>` adds a cost with the table's version
and source (Trustvian's `docs/local-development.md`, "Options").

In the WebUI of Terminal C's control plane:

- **Change Impact**, with the project chosen, lists its scenario executions;
  choose one to read the same report, one table per section. The `R1`…`C3` beside a
  behavior open that repetition's observations in Evidence.
  `http://127.0.0.1:<port>/#execution=<execution id>` opens it directly.
- **Overview**, with the project chosen, has a **Latest comparison** panel:
  the newest execution's verdict, its added, removed and lost counts, the
  four sameness answers and the first suggestion, with **Open in Change
  Impact**. For the run above: `Verdict fail · Added 1 · Removed 0 · Lost 0`,
  `Same scenario true · inputs true · model true · prompt not_recorded`.

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

## 8. Live mode: a fleet that keeps working

Steps 3–6 are runs that end. Live mode is one that does not: three agents,
each its own process, its own actor and its own Trustvian run, work a ticket
every few seconds until you stop them, so the live view fills continuously.

| Agent (`service.name`) | Tools | Tickets (eight each, e.g.) |
|---|---|---|
| `support-agent` | `lookup_customer`, `send_reply` | "How do I reset my password?" |
| `billing-agent` | `lookup_customer`, `lookup_invoice`, `issue_refund` | "I was charged twice this month." |
| `accounts-agent` | `lookup_customer`, `change_plan` | "Please upgrade me to Pro." |

`live.py` starts one `trustvian dev` per role, all attached to one control
plane that is already running:

```text
trustvian dev --api-url $TRUSTVIAN_API_URL --project trustvian-langgraph-quickstart \
  --agent <role>-agent --candidate live-<role> --instrumentation existing \
  -- python run.py
```

with `LIVE_ROLE=<role>` in its environment; `graph.py` sees `LIVE_ROLE` and
works that role's tickets with the same graph. dev exports `--agent` as
`OTEL_SERVICE_NAME` and starts a Collector of its own, and each role learns
into a baseline of its own (the candidate is dev's learning scope). Two
things happen on purpose, and rarely:

- **Drift.** Every 20th billing ticket also binds `export_customer` and asks
  for an export: a new behavior on an agent Trustvian has already learned.
- **Failed calls.** The fake CRM answers about 5% of requests with `503`
  (`429` for refunds). The tool returns a short failure to the model, which
  usually tries again.

Three terminals. **Terminal A**, the CRM from step 2. **Terminal C**, the
control plane every run attaches to, on a state directory of its own (the
standalone command from Trustvian's `docs/local-development.md`, "Running the
parts separately"):

```bash
trustvian-local --state-dir ~/.trustvian/live --listen 127.0.0.1:8080
```

It prints `Web: http://127.0.0.1:8080/`; open it. **Terminal B**, with step
3's exports:

```bash
export TRUSTVIAN_API_URL=http://127.0.0.1:8080
python live.py
```

Without `TRUSTVIAN_API_URL`, `live.py` exits with one line naming the
`trustvian-local` command above. It prints each run id as its dev reports it,
then one line per ticket, never its text:

```text
live: 3 agents (support-agent, billing-agent, accounts-agent), one run each on http://127.0.0.1:8080, one ticket each every ~10 s, until stopped (Ctrl-C)
live: watch at http://127.0.0.1:8080/
support-agent   run dev-live-support-20261012T101546.209Z
billing-agent   run dev-live-billing-20261012T101546.443Z
accounts-agent  run dev-live-accounts-20261012T101546.523Z
support-agent   ticket 1    tools: send_reply, lookup_customer  (3.6 s)
billing-agent   ticket 20   tools: issue_refund, lookup_invoice, lookup_customer, export_customer  (3.2 s)  failed calls: 1  [drift]
billing-agent   ticket 1    tools: issue_refund, lookup_invoice, lookup_customer  (4.9 s)  failed calls: 1
```

Stop it with **Ctrl-C** in Terminal B: `live.py` sends every dev `SIGINT`,
each stops its agent and completes its run (`… run dev-live-… complete`),
and `live.py` prints the tickets per agent and exits 0. A dev still running
after 20 s (`LIVE_STOP_GRACE_SECONDS`) is killed, its Collector and agent
with it. A dev that exits early is restarted after a back-off, as a new run
with a new card; the others keep working. Stop Terminal C afterwards; its
state keeps the runs.

**What you will see** in the WebUI's Live page:

- **Three cards under "Active now"**, `support-agent`, `billing-agent` and
  `accounts-agent`, each with its run id, the most recently active first.
- **The newest activity is followed**: the canvas and the Inspector switch
  to whichever agent sent the latest observations ("Following newest
  activity").
- **Click a card to follow that agent.** The view stays on it ("Pinned to
  your selection") while the other cards keep counting.
- **Follow active** goes back to following the newest activity.

What a 14-minute run showed (Trustvian v0.12.0, `qwen2.5:3b` on an Apple M3
Pro laptop, the Ollama app with its default settings):

- **Three cards, one per agent**, and three runs, each `completed` after
  Ctrl-C, which took about a second; no dev, Collector or agent was left
  running.
- **A steady stream.** 192 tickets (61, 64 and 67), about 2,700
  observations; a ticket took 2.9 s at the median and 30 s at most, while a
  headless browser was reading the page on the same machine.
- **Each agent's behaviors, in its own run:** the four `rpc/…` rows of
  LangGraph itself, `external/qwen2.5:3b → ollama`, `http/GET` and
  `http/POST → 127.0.0.1`, and the agent's tools: 9 for `support-agent` and
  `accounts-agent`, 11 for `billing-agent` (its three tools and the drift's
  `export_customer`).
- **The drift** came at billing tickets 20, 40 and 60.
- **Failed calls:** 14, each the `503` or `429` of one CRM request (5 for
  `support-agent`, 5 for `billing-agent`, 4 for `accounts-agent`); the runs
  went on.
- **Pinning held.** With the view following `billing-agent`, a click on
  `support-agent` read "Pinned to your selection"; 20 s later it still
  showed `support-agent` while the other cards kept counting, and **Follow
  active** went back to "Following newest activity".
- **Status shows one of the three.** Every dev's Collector reports to the
  control plane as `dev`, and the control plane holds one report per name,
  so `trustvian status` and the Status view show one agent's Collector at a
  time, whichever reported last: six reads 5 s apart named `accounts-agent`
  five times and `support-agent` once (under Compose, each of the three in
  turn). Each count is that one Collector's (`"received": "60",
  "evaluated": "60"`), not the fleet's.

What the live view does not do at Trustvian v0.12.0:

- **No pause.** The view keeps moving; to hold one agent still, pin its card.
  (The **Stop** under "Watch one run" stops watching a run, not the view.)
- **The canvas draws from the moment you select a run.** The stream keeps
  no history, so a pinned card's canvas fills as new observations arrive; a
  one-off such as the drift is drawn only if it arrives while that run is
  shown. The Live stream table below lists every agent's rows, whichever card
  is pinned. Earlier evidence is under Runs.

The knobs, all environment variables:

| Variable | Default | |
|---|---|---|
| `TRUSTVIAN_API_URL` | none; required | the control plane every dev attaches to |
| `LIVE_AGENTS` | `support,billing,accounts` | the roles to run, one dev each |
| `LIVE_INTERVAL_SECONDS` | `10` | one ticket per agent this often, ±50% jitter |
| `LIVE_DRIFT_EVERY` | `20` | every Nth billing ticket also exports; `0` = never |
| `LIVE_MAX_TICKETS` | `0` | tickets per agent, then that run completes; `0` = until stopped |
| `LIVE_STOP_GRACE_SECONDS` | `20` | how long Ctrl-C waits for the runs to complete |
| `CRM_ERROR_RATE` | `0.05` | share of CRM requests that fail; `0` = none. Read by `mock_services.py`, so set it in Terminal A |

The three agents share one model server. Ollama serves
`OLLAMA_NUM_PARALLEL` requests at a time and queues the rest, so a ticket can
wait for the other agents' model calls, and the median includes that wait.
A slower model needs a longer
`LIVE_INTERVAL_SECONDS`. Each role learns into its own baseline under
`~/.trustvian/dev/`, kept between sessions, so the next session is scored
against what this one taught.

With Docker Compose, live mode is a service of its own: `python live.py` in
one container, its three dev processes and three Collectors attached to the
stack's control plane with `TRUSTVIAN_API_URL=http://control-plane:8080`:

```bash
docker compose --profile live up -d       # builds its image the first time (after an upgrade: build it)
# open http://127.0.0.1:8080/
docker compose logs -f live               # the run ids and the per-ticket lines
docker compose --profile live down        # stops it; every dev completes its run
```

`down` keeps the volumes, so the next `up` is scored against what this one
taught; `down -v` forgets it. The knobs go in `.env`. The `agent` service
and its subcommands are unchanged.

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

Live mode (step 8) has tests of its own: `live.py` with a stub in place of
`trustvian` and a stub agent (one dev per role with its `--agent`,
`--candidate` and `LIVE_ROLE`, a missing `TRUSTVIAN_API_URL` refused,
`LIVE_MAX_TICKETS`, `LIVE_DRIFT_EVERY`, a crashed dev restarted as a new run,
nothing left running after SIGTERM, a dev that ignores SIGINT killed with its
agent), the CRM's new routes and seeded error rate, and each role's graph
with the scripted model, under the same content checks.

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

The first build clones Trustvian (`TRUSTVIAN_REF`, default `v0.12.0`) and
compiles `trustvian` and `trustvian-local`; `trustvian-collector` is copied
out of the signed release image
`ghcr.io/trustvian/trustvian-collector:v0.12.0`, pinned by digest
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
`export_customer` as the added behavior; Change Impact in the WebUI compares
the two runs as well.

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
checkout in the container, and the `agent` service sets `LLM_MODEL`, so the
model is recorded. Expected, as measured (44 s): the HTTP rows read `→ crm`,
then `tool/export_customer 0/3 3/3 + added`, `same_model true` with `model
qwen2.5:3b` on both sides, `PASS max llm calls per run: 4 (<= 18)`, `Gate:
FAIL`, exit 1.

Then the report, with the execution id from the first line:

```bash
docker compose run --rm agent trustvian eval report scn-support-graph-export-<…> --json
docker compose run --rm agent trustvian eval report scn-support-graph-export-<…> --format md
```

Its `comparison.counts` read `"rows": "10", "added": "1", "removed": "0",
"neither": "9", "not_recorded": "0", "lost": "0"`, as natively, and Change
Impact and Overview's Latest comparison show it at `http://127.0.0.1:8080/`.
The report names its producers: the CLI and control plane here are built from
v0.12.0's source rather than taken from the release archive, so they read

```text
Produced by `trustvian` `v0.0.0-20261013125534-23beffc7a85d 23beffc7a85db17cc22913769f6357953e88dfa0` and control plane `(devel) 23beffc7a85db17cc22913769f6357953e88dfa0`.
```

— the v0.12.0 commit, without the release's version string.

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
| Live is empty | `docker compose run --rm agent trustvian status`, or the WebUI's **Status** view: which Collector reports to the control plane, what it received and evaluated, and suggestions naming what to check. No Collector at all while `live` runs: is its image current (`docker compose --profile live build live`)? A dev from before v0.12.0 starts a Collector that does not report status |
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
| Live view is empty | Ask the pipeline: `trustvian status --api-url <the API line of dev's banner>` (or `$TRUSTVIAN_API_URL` in live mode) prints which Collector reports, the spans it received and evaluated, and each `service.name` it saw; its `suggestions` name what to check, for example `No Collector has reported in 30 s. Is 'trustvian dev' running, and is trustvian-collector on its path?`. The WebUI's **Status** view shows the same. `trustvian dev --check` tests the helpers with no workload: a reporting `dev-check` Collector and an empty `suggestions` list mean they work. A Collector that reports but has seen no producer points at the agent: does `run.py` print "exporter → http://127.0.0.1:.../v1/traces" at startup? If not, `opentelemetry-exporter-otlp-proto-http` is not installed in the venv |
| No `tool/` rows, only HTTP | `openinference-instrumentation-langchain` is not installed or too old; check with `pip show` |
| dev stops because of `OTEL_SDK_DISABLED=true` | Unset it. To silence LangChain's own tracer use `LANGSMITH_TRACING=false`, not that variable |
| `=== c-1001: stopped after 17 steps ===` | The model kept calling tools; the run still completes and its behaviors are recorded. Try a larger model via `LLM_MODEL` |
| `openai.OpenAIError: Missing credentials` | `LLM_BASE_URL` is set, so `ChatOpenAI` is used; export `OPENAI_API_KEY` (`EMPTY` for vLLM or Ollama) |
| Tool calls show up but all go to one host | Expected: the behavior is `tool/<name>`, read from the tool name; the HTTP request beneath it is a behavior of its own |
