# Marketplace review follow-up: 0.3.0

This release addresses the findings on submission #4368 against
`58b64e2362acf8d7b4597e81f42fdbe2cb662718`.

| Finding | Change and verification |
| --- | --- |
| Inherited setup PATH and mutable dependencies | Shell entry points use `/bin/bash`, a fixed PATH and `/usr/bin/python` with environment isolation. `runtime.py` installs the full committed version-and-SHA256 wheel lock, including pip, with `--require-hashes`, `--only-binary=:all:` and isolated pip configuration. There is no mutable pip upgrade or compatibility installer. Setup tests check the exact install arguments, failed-install marker handling, reuse and symlink rejection. A real locked installation also completed on Python 3.14. |
| Unbounded process/network output | `runner.py` limits complete helpers to 64 KiB output, 32 KiB buffered lines, 768 MiB address space and 256 descriptors. Finite helper deadlines are 25 seconds for commands/status, 35 seconds for discovery, 330 seconds for installation and 600 seconds for pairing. Internal pairing additionally has a 300-second deadline. Discovery subprocess output is bounded while streaming. Cache and credential reads have byte limits; device lists accept at most 32 validated IPv4 devices with bounded names and identifiers. |
| Stuck processes and detached descendants | Every helper runs under a process-group supervisor with TERM/KILL cleanup. Cleanup kills surviving descendants even when the direct child exits first. Detached backend supervisors watch the plugin component's lifetime process and bound lifetime to one hour. QML destruction stops its lifetime process and foreground helpers. Regression tests cover timeout, excess output, a descendant ignoring SIGTERM, and termination when the component owner ends. |
| Unbounded command/client work | The QML queue admits at most 32 unsent commands. Backend admission is capped at 16 clients and 4 watchers, command processing has a 12-second deadline, and keyboard focus notifications are coalesced. Typing feedback is bounded. |
| Network markup rendering | Plugin-owned Text components explicitly use `Text.PlainText`; metadata strings are bounded before serialization. Errors exposed to the UI are stable categories rather than arbitrary exception text. |
| Symlink-following state/runtime paths | `safe_io.py` walks directories through no-follow directory descriptors, validates ownership and writable permissions, opens regular files without following symlinks and uses private atomic writes. Runtime sockets live in a private directory under XDG_RUNTIME_DIR with no shared `/tmp` fallback. Cache and pyatv credential storage use the same helpers. The backend writes no persistent logs. Tests cover symlink reads/locks, atomic replacement without modifying the symlink target, and oversized input. |

Validation: 26 Python tests passed locally, plugin manifest validation passed,
shell syntax and whitespace checks passed. Live read-only checks confirmed
connection and Now Playing metadata. The shortcut editor was visually checked;
its JavaScript functions were exercised for saving, collision rejection,
cancellation, modifiers, TV-selection preservation and restoring defaults.
No real pairing prompts or remote-control commands were sent during release
verification because the TV was in use.

The focused investigation and review found two additional process-lifetime
issues; both were fixed and covered by the process-group/component-owner tests.
This is evidence for the stated fixes, not a claim of a comprehensive security
audit. Installation still downloads the documented locked dependencies into a
user-owned virtual environment and therefore still requires marketplace
maintainer review. Listing approval remains the marketplace's decision.
