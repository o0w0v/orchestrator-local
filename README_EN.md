# Orchestrator Local 0.7.2 — Delegation from your usual chat

With local delegation ON in a connected desktop chat, Luna briefly routes suitable deliverable work to Gemma or keeps it in the conversation. The current conversation performs the final lightweight review and necessary patches; it does not add another cloud reviewer or silently change the conversation model to Sol. Luna uses an existing ChatGPT-signed-in Codex CLI and consumes Cloud usage. OFF and per-request opt-out bypass both routing and new local generation.

Download the [Windows 0.7.2 installer](https://github.com/o0w0v/orchestrator-local/releases/download/v0.7.2/OrchestratorLocal-0.7.2-Setup.exe). See [release assets and checksums](https://github.com/o0w0v/orchestrator-local/releases/tag/v0.7.2), and [workflow, shared contracts, and evidence](docs/ROUTING_JA.md).

> Keep asking your usual AI as before. Share some of the work with an AI on your PC to reduce Cloud AI consumption.

**[日本語の導入手順・使い方](README.md)**

## Why use it?

The goal is to keep the familiar way of asking for work, receive results of the quality you need, and lower the cost of producing them. Handoffs, precise edits and file saving are the mechanisms behind that goal.

### Related evaluation

A new 500-case synthetic data comparison of Luna routing and lightweight review reported about 41.8% less Standard-equivalent usage, including routing, design, review and necessary corrections. Fixed-reference agreement was 500/500 for direct Sol and 499/500 for delegation; the mismatch involved an ambiguous starting evidence ID. See [conditions and limitations](docs/ROUTING_JA.md). This does not guarantee equal quality or the same savings in actual use.

See the [evaluation summary and original records](docs/EVALUATION_JA.md). This public application does not yet measure conversation-side Credits.

### What happens behind the scenes

The conversation AI handles consultation/design and final review, while Gemma does some of the work. Usable output is kept; necessary corrections are saved as precise edits. The [internal design](DESIGN_JA.md) and the implementation notes below explain this workflow.

## Supported work

CSV/JSON organization, summaries, short reports, and small app code drafts. For example, ask Codex to build a calculator: Codex chooses the scope, Gemma drafts the requested files, and Codex reviews, copies, runs and tests them. The application itself never edits a source repository or executes generated code. Large development tasks still need a scoped handoff or direct Codex work. See the [code workflow](docs/CODE_JA.md).

When custom MCP tools are unavailable in a conversation with shell access, the installed Skill can use its bundled bridge to the same tool handlers. Users do not need to enter commands. Both paths retain the same ON/OFF guard, request deduplication and review/save workflow. This capability check does not establish coding cost savings; conversation-side Credits remain unmeasured.

## Windows desktop download

Download and open the [Windows installer](https://github.com/o0w0v/orchestrator-local/releases/download/v0.7.2/OrchestratorLocal-0.7.2-Setup.exe), then follow the Next buttons. Python is bundled and administrator rights are not needed. Existing Ollama and Gemma4:26b are required; Luna routing also needs an existing ChatGPT-signed-in Codex CLI. Models and the CLI are not downloaded automatically.

The guided setup detects the previous registered installation, preserves its data/model paths and Startup preference, backs up settings, and updates the Codex connection. It refuses to overwrite custom Skills or interrupt active jobs. Restart the Orchestrator Local MCP connection in desktop settings and open a new chat; restart the app if needed. Then use the large central power control from the Start menu: a green ring and ON text mean enabled; a gray ring and OFF text mean disabled. Enter and Space also activate the focused control. Initial delegation is OFF. Turning OFF bypasses new Luna routing and blocks new and queued local starts; running work may finish. The Skill stays registered, and a request not to use local work takes priority even while ON. Details holds optional settings/history. See the [GUI guide](docs/GUI_JA.md) and [unsigned preview release](https://github.com/o0w0v/orchestrator-local/releases/tag/v0.7.2). A portable ZIP remains available.

## Source installation

The source edition is for Windows users who already have Python 3.11+ and a working Ollama installation with `gemma4:26b`. Model weights, Ollama, Python, user configuration, job data and credentials are not included. This is not a one-click installer or a reviewed plugin-directory listing. macOS/Linux and other machines have not been acceptance tested.

The model creates candidates only. The conversation checks them against the original request, accepts usable output, or patches errors that affect use. It does not regenerate results to improve style. Files and SQLite jobs survive MCP reconnects; failed or interrupted generations are not retried automatically.

The local service talks only to a configured loopback Ollama endpoint. Inputs and candidates are also returned to the conversation for review, so this is not an entirely offline workflow. Conversation usage is not measured by this application, and cost savings are not guaranteed.

See [validation and scope](VALIDATION.md), [the design](DESIGN_JA.md), and the repository [license](LICENSE).

Historical development and experiment records live in [OrchestratorMD](https://github.com/o0w0v/OrchestratorMD). This application was extracted from the [previous source snapshot](https://github.com/o0w0v/OrchestratorMD/tree/d95881af188056933886d148f0bc0a5ea7c2e664/apps/orchestrator-local).
