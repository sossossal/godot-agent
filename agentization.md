---
summary: "Design principles and execution chain for turning deterministic features into agent capabilities"
read_when:
  - You want to turn a normal operation into an agent tool
  - You want to borrow Moltbot agent architecture in another project
  - You need a detailed map of the agentization layers beyond the basic agent loop
---
# Agentization Patterns

Last updated: 2026-04-20

This document explains how Moltbot turns ordinary product capabilities into
agent-accessible capabilities, and which design choices are most worth copying
into another project.

If [Agent Loop](/concepts/agent-loop) explains the runtime lifecycle, this doc
explains the architectural pattern behind that lifecycle:

- what "agentized" means in Moltbot
- which boundaries are explicit in code
- how a feature moves from deterministic logic into an agent tool
- which parts should remain outside the LLM

See also:

- [Gateway architecture](/concepts/architecture)
- [Agent Runtime](/concepts/agent)
- [System Prompt](/concepts/system-prompt)
- [Plugins](/plugin)
- [Multi-Agent Sandbox & Tools](/multi-agent-sandbox-tools)
- [Gateway Security](/gateway/security)

## What agentization means in Moltbot

In Moltbot, "agentizing" a capability does **not** mean:

- writing a bigger prompt
- adding one more branch to a giant chat handler
- letting the model improvise shell commands with no contract

It means turning a capability into an explicit runtime surface with:

- a stable entry point
- typed inputs
- a bounded execution environment
- a structured result
- policy and sandbox controls
- a place in the tool inventory shown to the model

In practice, Moltbot splits a capability into at least two layers:

1. A deterministic implementation layer
2. An agent exposure layer

The deterministic layer does the real work:

- send a message
- call `ffmpeg`
- move files
- query a remote API
- inspect a node
- start a browser action

The agent exposure layer decides how that work becomes available:

- as a tool for the LLM
- as a direct command
- as a gateway method
- as a lifecycle hook

This distinction is central to the codebase.

## The four main exposure surfaces

Moltbot does not force every feature through the LLM. Instead, it defines
multiple surfaces, each for a different class of work.

### Tool

Use a tool when the model should be able to decide **when** and **how** to call
the capability during a run.

A tool is the main "agentized" surface. The structure is the familiar:

- `name`
- `description`
- `parameters`
- `execute(...)`

Representative examples:

- core tools in `src/agents/tools/*`
- plugin tools registered through `api.registerTool(...)`

Relevant implementation anchors:

- `src/agents/tools/common.ts`
- `src/agents/tools/message-tool.ts`
- `src/plugins/types.ts`
- `src/plugins/registry.ts`

### Command

Use a command when the user wants a deterministic shortcut that should bypass
the LLM completely.

This is the right choice for:

- toggles
- status reads
- fixed actions with little ambiguity
- operator workflows where natural-language planning adds no value

Moltbot makes this distinction explicit with `registerCommand(...)` in the
plugin API instead of pretending every feature should be an agent tool.

### Gateway method

Use a gateway method when the capability should be callable remotely over the
control plane by:

- a UI
- the CLI
- automation
- another process
- another agent surface

This is the RPC/API face of a capability.

### Hook

Use a hook when the capability should execute **because an event happened**, not
because the model deliberately chose it.

Typical examples:

- mutate context before a run starts
- inspect final messages after a run
- observe tool calls
- respond to inbound or outbound message lifecycle events

## The most reusable design principles

These are the parts most worth borrowing into another project.

### 1. Build a control plane, not a chat handler

Moltbot treats the AI system as a control plane with multiple clients and event
streams, not as one monolithic chat callback.

The gateway is the center of gravity:

- clients connect to one long-lived server
- channels feed messages into it
- agent runs emit stream events out of it
- tools and gateway methods live behind the same control plane

Why this matters:

- you can add new interfaces without duplicating agent logic
- side effects can be observed and streamed consistently
- UI, CLI, nodes, and automations stay on one protocol

Implementation anchors:

- `src/gateway/server.impl.ts`
- `src/gateway/server-chat.ts`
- `src/gateway/server-http.ts`

Borrow this if your project is already growing beyond a single web chat box.

### 2. Route before execution

Moltbot resolves **who should run** and **which session should own the run**
before it executes any model call.

The route resolution layer computes things like:

- `agentId`
- `sessionKey`
- whether the message belongs to main or isolated context
- which channel or peer identity is in scope

Why this matters:

- multi-agent becomes configuration, not custom branching
- channels can share runtime code
- session isolation becomes predictable
- policy can depend on route identity

Implementation anchor:

- `src/routing/resolve-route.ts`

A lot of agent projects get this backwards. They start a model call first and
only later try to figure out isolation and routing. Moltbot gets the identity
model correct up front.

### 3. Treat sessions as first-class state

In Moltbot, a session is not just chat history. It also carries:

- routing identity
- per-session settings
- persisted thinking and verbose overrides
- skills snapshot linkage
- stream lifecycle state

This is why session resolution happens early in the command path and why runs
serialize by session lane.

Why this matters:

- concurrent turns do not corrupt transcripts
- compaction, retries, and followups have a stable boundary
- per-session overrides survive beyond one prompt

Implementation anchors:

- `src/commands/agent.ts`
- `src/commands/agent/session.ts`
- `docs/concepts/agent-loop.md`

### 4. Keep deterministic logic outside the tool wrapper

This is one of the most important engineering rules in the project.

The best tools are thin wrappers around deterministic code. The wrapper should:

- validate and normalize params
- resolve runtime context
- call the deterministic function
- map the result to a tool payload

The wrapper should **not** become the place where all business logic lives.

Why this matters:

- the capability can also be exposed as a command or gateway method
- tests can target the deterministic layer without spinning an agent run
- the agent layer stays small and easier to review

`voice-call` is a good example of the correct direction: one capability is
exposed both as gateway methods and as an agent tool, instead of copying the
business logic into two unrelated places.

Implementation anchors:

- `extensions/voice-call/index.ts`
- `src/process/exec.ts`

### 5. Make capabilities typed tools, not prompt folklore

Moltbot does not rely on "the model knows how to do this if we describe it in
English". A real capability becomes a typed tool with explicit parameters.

Why this matters:

- the LLM sees an actual interface
- validation happens before side effects
- tool usage is inspectable and streamable
- docs and system prompt can remain compact and factual

This also makes it practical to implement large tools with a single `action`
field and a structured schema, rather than exploding the tool count.

Representative examples:

- `message`
- `voice_call`
- `llm-task`

### 6. Separate registration from policy

Moltbot first resolves the full candidate tool set, then filters it by policy.

That separation is critical.

Registration answers:

- what tools exist
- which plugin provided them
- whether they are optional

Policy answers:

- which tools are allowed for this run
- which tools are denied
- which group expansions apply
- how sandbox and subagent restrictions affect the final set

Why this matters:

- a plugin can register tools once without encoding every security rule
- policy precedence stays explicit
- UI and debug tooling can reason about the difference between "available" and
  "allowed"

Implementation anchors:

- `src/plugins/tools.ts`
- `src/agents/tool-policy.ts`
- `src/agents/pi-tools.policy.ts`
- `src/agents/pi-tools.ts`

### 7. Make runtime assembly dynamic per run

Moltbot assembles the actual agent runtime for each run from:

- route identity
- session state
- workspace
- bootstrap files
- skills snapshot
- model selection
- auth profile
- tool inventory
- policy filters
- sandbox state

Why this matters:

- one agent runtime can support many distinct run shapes
- the same system can support main sessions, subagents, sandboxes, channels, and
  automations without forking core logic
- prompt size and tool list can stay accurate to the actual run

Implementation anchors:

- `src/commands/agent.ts`
- `src/agents/pi-embedded-runner/run.ts`
- `src/agents/pi-embedded-runner/run/attempt.ts`
- `src/agents/system-prompt.ts`

### 8. Expose a stable plugin runtime facade

Plugins in Moltbot do not need unrestricted access to arbitrary internals.
Instead, they receive a stable runtime facade.

This facade includes things like:

- config helpers
- media helpers
- channel helpers
- memory helpers
- command execution helpers
- logging

Why this matters:

- plugin authors depend on a supported contract
- internal refactors stay easier
- capabilities like `runCommandWithTimeout(...)` can be reused safely

Implementation anchors:

- `src/plugins/types.ts`
- `src/plugins/runtime/index.ts`
- `src/plugins/runtime/types.ts`

This is a very strong pattern for any project that wants third-party or
workspace-local extensions.

### 9. Keep optional and heavy capabilities additive

Not every tool should appear by default.

Moltbot explicitly supports:

- optional plugin tools
- allowlist-based exposure of those tools
- bundled plugins that are still disabled by default

Why this matters:

- heavy features do not pollute every run
- risky tools can remain opt-in
- niche capabilities do not bloat the default prompt/tool inventory

Implementation anchors:

- `src/plugins/tools.ts`
- `src/plugins/config-state.ts`
- `src/plugins/loader.ts`

### 10. Make sandbox defaults concrete

Moltbot treats sandboxing as an explicit execution boundary with real allow and
deny defaults, not just a prompt instruction.

The default sandbox policy allows a small safe core and denies higher-risk
surfaces such as:

- browser control
- canvas
- nodes
- cron
- gateway mutation
- channel-specific send surfaces

Why this matters:

- a "safe mode" is real, not aspirational
- non-main or untrusted sessions can be constrained by construction
- policy debugging becomes possible

Implementation anchors:

- `src/agents/sandbox/constants.ts`
- `docs/gateway/sandboxing.md`
- `docs/multi-agent-sandbox-tools.md`

### 11. Stream events as first-class runtime outputs

Moltbot does not wait until the end of the run to surface what happened.

The runtime streams:

- lifecycle events
- assistant deltas
- tool events

Why this matters:

- UIs can show live status
- operators can debug runs without reading a final blob
- long-running tools feel connected to the control plane

Implementation anchors:

- `src/gateway/server-chat.ts`
- `src/agents/pi-embedded-runner/run/attempt.ts`
- [Agent Loop](/concepts/agent-loop)

### 12. Return structured results, not chatty prose

Moltbot tools generally return structured payloads, often as JSON-shaped details
plus a renderable textual content block.

Why this matters:

- tools can be chained
- results are easier to persist and inspect
- downstream components can reason about details without scraping prose

Implementation anchor:

- `src/agents/tools/common.ts`

### 13. Reuse the same capability across surfaces

A mature system should let one capability appear in multiple places:

- agent tool for LLM planning
- gateway method for remote invocation
- command for direct operator use
- hook for lifecycle automation

This lets you keep the business logic centralized while exposing it through the
surface that best matches the job.

Moltbot already does this in several places, especially in extension code.

### 14. Prefer thin channels and rich shared runtime

Moltbot keeps channel-specific code mostly responsible for:

- ingestion
- normalization
- delivery
- provider-specific actions

The shared runtime owns:

- route resolution
- sessions
- tools
- prompt assembly
- policy
- streaming

Why this matters:

- new channels are cheaper to add
- bug fixes in agent behavior benefit all channels
- security and policy stay centralized

Implementation anchors:

- `src/channels/registry.ts`
- `src/routing/resolve-route.ts`
- `src/agents/*`

## The agentization execution chain

The following chain is the practical answer to "what happens when a capability
has been agentized in Moltbot?"

### 1. Ingress arrives through a gateway surface

A run can start from several entry points:

- gateway RPC
- CLI `agent`
- webhook or automation
- a chat provider message that resolves to an agent turn

The important point is that the run does not begin inside a random channel
handler. It enters a shared control plane.

Primary anchors:

- `src/gateway/server.impl.ts`
- `src/commands/agent.ts`

### 2. Route identity is resolved

The system computes the effective route:

- `agentId`
- `sessionKey`
- channel and peer identity
- whether the route is main, group, thread, slash, or otherwise isolated

Primary anchor:

- `src/routing/resolve-route.ts`

### 3. Session metadata is resolved and persisted

Before the runtime starts, Moltbot resolves:

- session id and file
- whether the run is fresh or reused
- persisted thinking and verbose settings
- session-level skills snapshot needs

Primary anchors:

- `src/commands/agent.ts`
- `src/commands/agent/session.ts`

### 4. Workspace and bootstrap context are assembled

The run now gains its working context:

- workspace directory
- bootstrap files like `AGENTS.md`
- skills snapshot and skills prompt metadata
- any hook-provided injected context

Primary anchors:

- `src/agents/pi-embedded-runner/run/attempt.ts`
- `src/agents/system-prompt.ts`
- [Agent Runtime](/concepts/agent)

### 5. Core and plugin tools are resolved

Moltbot builds the initial tool inventory from:

- coding/runtime tools
- native Moltbot tools
- plugin tools

Primary anchors:

- `src/agents/pi-tools.ts`
- `src/agents/moltbot-tools.ts`
- `src/plugins/tools.ts`

### 6. Tool policy filters the inventory

The candidate tool set is then filtered through several policy layers such as:

- profile policy
- provider policy
- global policy
- agent policy
- group policy
- sandbox policy
- subagent policy

Primary anchors:

- `src/agents/tool-policy.ts`
- `src/agents/pi-tools.policy.ts`
- `src/agents/pi-tools.ts`

This is where "registered" becomes "actually callable in this run".

### 7. System prompt is built from the actual run shape

The system prompt is rendered using the final run context, including:

- tool names
- tool summaries
- workspace metadata
- runtime metadata
- sandbox hints
- skill inventory
- injected bootstrap content

Primary anchor:

- `src/agents/system-prompt.ts`

This detail is easy to miss: the prompt is downstream of tool resolution. That
means the model sees the tools it can actually call, not a fictional superset.

### 8. The embedded agent session is created

At this point Moltbot opens the session machinery and starts the real model
runtime:

- opens and guards `SessionManager`
- prepares the session file
- creates the actual agent session
- resolves prompt mode such as full or minimal for subagents
- subscribes to runtime events

Primary anchors:

- `src/agents/pi-embedded-runner/run.ts`
- `src/agents/pi-embedded-runner/run/attempt.ts`

Important details:

- subagents use a smaller prompt mode
- runs serialize by session lane
- hook points like `before_agent_start` and `agent_end` are available inside the
  runtime

### 9. The model plans and calls tools

Now the LLM can:

- produce assistant output
- call registered tools with validated parameters
- receive structured tool results
- continue reasoning with those results

If a tool is backed by deterministic code, the LLM only decides **that** it
should call the tool and **with which inputs**. The actual side effect is still
owned by application code.

### 10. Tool calls execute in deterministic code

This is the real "agentized feature" moment.

A tool executes its implementation layer, which may:

- call internal application services
- invoke remote APIs
- call `runCommandWithTimeout(...)`
- read or write workspace files
- dispatch a message
- inspect or control a node

The important boundary is that the LLM is no longer improvising. It is invoking
an owned capability through a stable contract.

### 11. Runtime events are streamed while the run is active

As the run progresses, Moltbot streams:

- assistant deltas
- tool start and finish events
- lifecycle events

This is how WebChat, Control UI, CLI, and other clients stay synchronized with
the live run.

### 12. Final payloads are persisted and fanned out

At the end of the run, Moltbot:

- persists transcript state
- emits final lifecycle events
- shapes final reply payloads
- dispatches the response to the correct surface

This closes the loop between route identity, tool execution, persistence, and
delivery.

## How to turn a normal operation into an agentized feature

This is the practical recipe to copy into another project.

### 1. Write the deterministic capability first

Start with ordinary application code.

Examples:

- `trimVideo(input, output, start, duration)`
- `organizeOfficeFolder(root, rules)`
- `sendInvoiceReminder(customerId)`
- `captureNodeScreenshot(nodeId)`

The function should be testable without an LLM.

This is the layer you want to keep stable.

### 2. Decide the correct exposure surface

Ask which of these is true:

- The model should decide when to use it: make it a tool.
- Operators should invoke it directly: add a command.
- Other clients or systems should call it: add a gateway method.
- It should run on lifecycle events: add a hook.

Many features should expose more than one surface.

### 3. Define a schema, not a free-form prompt

Once you decide the feature should be agent-callable, define structured inputs.

Good tool inputs:

- explicit required fields
- constrained `action` enums when one tool supports several operations
- paths, ids, booleans, and numbers represented as actual fields

Bad tool inputs:

- "tell me what to do with this"
- "command" as a giant shell string
- implicit output location rules that only exist in prose

### 4. Wrap the capability in a tool object

The tool wrapper should:

- normalize args
- validate required params
- resolve contextual defaults
- call the deterministic layer
- return a structured result

This is exactly the shape used throughout Moltbot core and plugins.

### 5. Register it through the plugin API by default

For most new features, the right starting point is a plugin, not a core change.

Why:

- you avoid bloating the default tool inventory
- you keep runtime dependencies localized
- you can opt the capability in or out
- you preserve a cleaner core

Primary anchors:

- `src/plugins/types.ts`
- `src/plugins/registry.ts`
- `src/plugins/loader.ts`

### 6. Use the plugin runtime for side effects

If the capability needs external execution, call the stable runtime facade
rather than reaching into arbitrary internals.

For example:

- `api.runtime.system.runCommandWithTimeout(...)`
- media helpers
- config helpers
- channel helpers

This is the pattern to use for capabilities backed by binaries like `ffmpeg`.

### 7. Decide whether the tool should be optional

Some tools should only appear when explicitly allowed.

This is a good fit for:

- heavy capabilities
- organization-specific plugins
- risky tools
- features with large dependency trees

Moltbot supports this explicitly instead of overloading global config with
special cases.

### 8. Add policy and sandbox expectations

Before shipping the tool, decide:

- should it be available in sandbox
- should it be denied in subagents
- should it belong to a tool group
- does it need separate elevated behavior

Do not rely on "the model will probably use it responsibly".

### 9. Return structured results

Tool output should give downstream code a stable contract.

Typical return shape:

- short human-readable content
- machine-readable `details`
- file paths or ids for created artifacts

For large artifacts, return references and metadata rather than embedding
everything in the tool response.

### 10. Add at least one non-agent surface if operators need it

A mature feature is often easier to test and operate when it also has:

- a command
- a gateway method
- or both

That gives you:

- direct manual testing
- easier automation
- clearer separation between business logic and LLM orchestration

### 11. Document the capability where operators will look

The final step of agentization is documentation:

- what the tool does
- what it does not do
- expected inputs and outputs
- policy and sandbox behavior
- example flows

Without this, a tool remains technically agentized but operationally opaque.

## When not to agentize a capability

Not every feature should become a tool.

Do **not** agentize when:

- the action is always deterministic and user-triggered with no need for model
  planning
- the action is too risky to expose to the LLM at all
- the feature is just a transport concern and belongs in channel plumbing
- the capability should run only as a lifecycle side effect

In those cases, use:

- command
- gateway method
- hook
- internal service only

## A practical borrowing order for other projects

If another project wants to copy these ideas, the best order is:

1. Build route resolution and session identity first.
2. Introduce a real tool contract with schemas and deterministic wrappers.
3. Separate registration from policy.
4. Add a plugin runtime facade before adding many plugins.
5. Add sandbox and explicit allow/deny policy.
6. Add streaming events and operator-visible lifecycle state.
7. Only then expand to multiple channels and external clients.

This order matters because it gives you the correct core boundaries before you
scale the surface area.

## Concrete example: video editing and office file organization

Suppose another project wants two new agentized capabilities:

- video editing
- office document organization

The Moltbot-style approach would be:

1. Implement deterministic functions first.
   - `probeVideo(...)`
   - `trimVideo(...)`
   - `extractAudio(...)`
   - `scanOfficeFolder(...)`
   - `classifyOfficeFiles(...)`
   - `renameAndMoveFiles(...)`
2. Wrap them as tools such as:
   - `video_edit`
   - `office_organizer`
3. Give each tool a schema with explicit actions.
4. Register them in a plugin.
5. Use the plugin runtime to call `ffprobe` and `ffmpeg` or file-system helpers.
6. Return structured file paths and summaries.
7. Optionally expose gateway methods for direct UI or automation use.
8. Keep them optional until the operational shape is stable.

That is a better design than:

- letting the model construct arbitrary shell commands
- putting all video logic inside one giant `execute(...)`
- exposing the feature only through prose in the prompt

## Current implementation anchors in Moltbot

The following files are the most useful starting points if you want to study the
actual implementation:

- `src/gateway/server.impl.ts`
  - gateway entry point
- `src/gateway/server-chat.ts`
  - agent event streaming and chat fanout
- `src/routing/resolve-route.ts`
  - route identity resolution
- `src/commands/agent.ts`
  - top-level agent command flow
- `src/commands/agent/session.ts`
  - session resolution
- `src/agents/pi-embedded-runner/run.ts`
  - embedded agent runtime entry
- `src/agents/pi-embedded-runner/run/attempt.ts`
  - session manager, prompt mode, hooks, subscription wiring
- `src/agents/system-prompt.ts`
  - tool-aware system prompt assembly
- `src/agents/pi-tools.ts`
  - tool set assembly plus policy filtering chain
- `src/agents/tool-policy.ts`
  - tool groups and policy expansion
- `src/agents/pi-tools.policy.ts`
  - low-level policy filter implementation
- `src/agents/sandbox/constants.ts`
  - default sandbox allow and deny behavior
- `src/agents/moltbot-tools.ts`
  - Moltbot native tool registration
- `src/agents/tools/common.ts`
  - common tool result helpers
- `src/plugins/types.ts`
  - plugin API contract
- `src/plugins/registry.ts`
  - plugin registration surface
- `src/plugins/loader.ts`
  - plugin loading and enable-state logic
- `src/plugins/tools.ts`
  - plugin tool resolution and optional exposure
- `src/plugins/runtime/index.ts`
  - stable plugin runtime facade
- `src/process/exec.ts`
  - controlled external command execution

## Summary

The most important lesson from Moltbot is this:

Agentization is not a prompt-writing exercise. It is a runtime architecture
exercise.

Moltbot works because it treats:

- routing
- sessions
- tools
- policy
- plugins
- sandboxing
- streaming
- delivery

as separate layers with explicit contracts.

That separation is what makes the system extensible, reviewable, and safer to
grow.
