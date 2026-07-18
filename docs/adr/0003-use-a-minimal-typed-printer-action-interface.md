# Use a minimal typed Printer-action interface

The Printer-action module exposes two entry points: `submit(ActionRequest)` for Action acceptance and `watch(Watch)` for Printer snapshots and action outcomes. Action requests use a closed typed union of named Printer actions; action definitions and all protocol, policy, Supervised-validation, journal, snapshot, and adapter knowledge remain private implementation, avoiding both a generic schema catalog and a wide method-per-action interface.
