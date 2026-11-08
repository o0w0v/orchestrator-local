# Validation of the Windows preview

## Local delegation switch 0.3.0

The default home is a compact ON/OFF control. Setup and history are optional Details panels. The persisted local-delegation preference starts OFF, including when an older job database first gains the control table. The switch retains Skill registration and does not rewrite Codex skill configuration.

All 24 source tests passed, including a connected MCP session switching OFF without reconnecting, rejection of new jobs, holding queued work, allowing running work to finish and saved candidates to be finalized, persistent state across Store instances, the compact GUI button, and refusal to enable through a legacy runner. The Skill's instruction changes give conversation requests not to use it priority; this instruction-level behavior is not a separate model evaluation.

The actual Windows bundle smoke test additionally verifies initial OFF, hot OFF with the same MCP connection, no new fake model call while OFF, the hidden Details panel, and saving an existing candidate while OFF. Fake responses and temporary settings are used throughout. Real user settings and model weights are not changed.

## Desktop edition 0.2.0

The desktop edition adds setup/status/history controls and a Python-bundled Windows x64 ZIP. The application still uses the same service, Store, worker and conversation-side review. It does not add a model call or adopt a candidate from the GUI.

The source suite contains 19 tests, including temporary registration/removal, preserving conflicting Startup shortcuts, input import without overwrite, service singleton start/stop, candidate versus completed-result access, frozen command paths and Tk widget rendering.

`packaging/smoke_windows.py` exercises the actual EXEs with Python removed from child PATH: temporary connection and Startup registration, singleton service startup without generation, official MCP stdio client with eight tools, one fake backend generation, GUI status before/after review, acceptance and saved artifacts, and clean service shutdown. All paths point into a temporary profile; no real model or paid Cloud is used. The suite does not prove behavior on a different PC or through an OS login/reboot.

Build instructions and the GUI workflow are in [docs/GUI_JA.md](docs/GUI_JA.md). The unsigned distribution includes dependency notices, Python's license, and file/archive SHA-256 checksums. The earlier manual real-model acceptance below applies to the underlying worker and is not a new GUI inference test.

Validated on Windows with Python 3.11, MCP Python SDK 1.30.0, an existing Ollama installation, and Gemma4 26B. Other-PC acceptance testing has not been performed.

## Automated checks

Run from this directory after installing `requirements.lock`:

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
```

Tests use the official MCP stdio client and a fake HTTP model backend. They cover request deduplication, reconnects, candidate acceptance, strict patches and result revisions, input paths and limits, CSV escaping, cancellation, failed/incomplete output, cold startup readiness, service interruption without automatic regeneration, and preservation of unrelated settings during registration/removal. No real inference or paid Cloud call is part of the automated suite.

The publication snapshot passed all 13 tests, including clean setup and removal from a source path containing spaces, using only temporary configuration, Skill and data directories.

## Manual acceptance already performed

- One real Gemma inference produced the expected allocation data: available stock 12; order 7 with lot 2 received 6 and backorder 1; the next order received 4; a cancelled order was excluded; remaining stock was 2.
- The conversation corrected only the unit in the report (`1件` to `1個`) and saved JSON, CSV and Markdown. No regeneration or extra Cloud reviewer was used. All saved file hashes matched their manifest.
- An actual Windows Startup shortcut launched the service. Launching it a second time retained the same service; neither launch created a job. An OS logout/reboot test was not performed.
- Existing user configuration was preserved. The same official stdio interface was exercised; the client app still needs to reload the registered MCP and Skill before first use. This does not claim end-to-end acceptance on every ChatGPT surface.

Two development failures were retained locally: an early stdio-owned child was interrupted, and cold-start readiness timed out before generation. They are not hidden retries of the successful inference. Local paths and private acceptance records are excluded from the source release.

This is functional validation of the application, not an independent audit of the prose or a general quality/cost guarantee. The separate 100-case synthetic study is linked from the repository README; it is not rerun during installation or tests.
