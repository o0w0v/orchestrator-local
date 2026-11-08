# Orchestrator Local

Standalone Windows Python application for CSV/JSON jobs using local Gemma and conversation-side review. The application does not edit a user's source repository or run arbitrary generated code.

Run `python -X utf8 -B -m unittest discover -s tests -v` from the repository root with the application dependencies installed. Tests use a fake backend and temporary settings/data paths. Do not add live inference, downloads, paid Cloud calls or changes to actual user registrations to the test suite.

Keep user settings, credentials, SQLite jobs, runtime logs, model files, virtual environments and installation receipts out of commits. Preserve existing results and unrelated MCP/Skill settings. Usable candidates are accepted without optional rewrites; necessary patches are checked against the original request. Changes to business requirements must come from the user.

Historical experiments and Rust coding-worker policies are kept separately in https://github.com/o0w0v/OrchestratorMD and do not define this application's runtime or test commands.
