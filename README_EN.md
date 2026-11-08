# Orchestrator Local 0.5.0 — Windows preview

> Keep asking your usual AI as before. Share some of the work with an AI on your PC to reduce Cloud AI consumption.

**[日本語の導入手順・使い方](README.md)**

## Why use it?

The goal is to keep the familiar way of asking for work, receive results of the quality you need, and lower the cost of producing them. Handoffs, precise edits and file saving are the mechanisms behind that goal.

### Related evaluation

A 100-case synthetic comparison reported about 32.78% less known Cloud Credits consumption, including Sol review and partial corrections, with correct adopted data in both methods for all 100 cases. Mean active time increased from 63.10 to 247.32 seconds on the RTX 3080 10GB test PC.

See the [evaluation summary and original records](docs/EVALUATION_JA.md). This public application does not yet measure conversation-side Credits.

### What happens behind the scenes

The conversation AI handles consultation/design and final review, while Gemma does some of the work. Usable output is kept; necessary corrections are saved as precise edits. The [internal design](DESIGN_JA.md) and the implementation notes below explain this workflow.

## Windows desktop download

Download and open the [Windows installer](https://github.com/o0w0v/orchestrator-local/releases/download/v0.5.0/OrchestratorLocal-0.5.0-Setup.exe), then follow the Next buttons. Python is bundled and administrator rights are not needed. Existing Ollama and Gemma4:26b are required; models are not downloaded automatically.

The guided setup detects the previous registered installation, preserves its data/model paths and Startup preference, backs up settings, and updates the Codex connection. It refuses to overwrite custom Skills or interrupt active jobs. Restart Codex once after installation and open a new conversation. Then use the large central power control from the Start menu: a green ring and ON text mean enabled; a gray ring and OFF text mean disabled. Enter and Space also activate the focused control. Initial delegation is OFF. Turning OFF blocks new and queued local starts; running work may finish. The Skill stays registered, and a request not to use local work takes priority even while ON. Details holds optional settings/history. See the [GUI guide](docs/GUI_JA.md) and [unsigned preview release](https://github.com/o0w0v/orchestrator-local/releases/tag/v0.5.0). A portable ZIP remains available.

## Source installation

The source edition is for Windows users who already have Python 3.11+ and a working Ollama installation with `gemma4:26b`. Model weights, Ollama, Python, user configuration, job data and credentials are not included. This is not a one-click installer or a reviewed plugin-directory listing. macOS/Linux and other machines have not been acceptance tested.

The model creates candidates only. The conversation checks them against the original request, accepts usable output, or patches errors that affect use. It does not regenerate results to improve style. Files and SQLite jobs survive MCP reconnects; failed or interrupted generations are not retried automatically.

The local service talks only to a configured loopback Ollama endpoint. Inputs and candidates are also returned to the conversation for review, so this is not an entirely offline workflow. Conversation usage is not measured by this application, and cost savings are not guaranteed.

See [validation and scope](VALIDATION.md), [the design](DESIGN_JA.md), and the repository [license](LICENSE).

Historical development and experiment records live in [OrchestratorMD](https://github.com/o0w0v/OrchestratorMD). This application was extracted from the [previous source snapshot](https://github.com/o0w0v/OrchestratorMD/tree/d95881af188056933886d148f0bc0a5ea7c2e664/apps/orchestrator-local).
