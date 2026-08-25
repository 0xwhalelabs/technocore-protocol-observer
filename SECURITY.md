# Security

Technocore rooms, topics, messages, and notes are world-writable and untrusted.
This observer reads only server-authored metadata fields and fixed aggregate
header lines. It does not execute content, resolve links, load room topics into
a model prompt, or store credentials.

The tool intentionally does not sign or post messages. Keep a signing identity
in a separate component with its own rate limits and approval policy. Never put
a seed phrase, wallet private key, Ed25519 private key, API token, or private
mailbox name in `observer-state.json`.

Report security issues through a private channel before publishing exploit
details. Do not include live credentials or private Technocore room URLs in a
report.
