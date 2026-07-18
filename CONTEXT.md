# Printer Control

Language for requesting and supervising changes to a printer's state or behavior.

## Language

**Printer action**:
An operator-requested change to a printer's state or behavior, such as pausing a print or setting a target temperature.
_Avoid_: Command, control message

**Protective action**:
A Printer action whose sole purpose is to reduce immediate physical risk, such as stopping a print or turning heaters off. It remains permissible when the printer's current state cannot be confirmed.
_Avoid_: Emergency command, normal action

**Action acceptance**:
The determination that a Printer action is permitted and has been submitted for execution. Acceptance is not evidence that the printer's physical state changed.
_Avoid_: Success, confirmation

**Action confirmation**:
Observation that the printer reached the outcome expected from an accepted Printer action.
_Avoid_: Delivery, acknowledgement, acceptance

**Action request**:
A uniquely identified request to perform one Printer action. Repeating the same request does not authorize an additional physical effect.
_Avoid_: Command, event

**Indeterminate action**:
An accepted Printer action whose physical outcome can be neither confirmed nor disproved.
_Avoid_: Failed action, successful action

**Superseded action**:
An accepted Printer action whose intended outcome was replaced by a newer Action request before confirmation.
_Avoid_: Failed action, cancelled action

**Compound action**:
A Printer action that requires an ordered series of operations, including any restoration needed to leave the printer in a known state.
_Avoid_: Macro, command sequence

**Supervised validation**:
Human-observed execution used to establish that changed Printer-action behavior produces the intended physical result. Once established for unchanged behavior, routine operation does not require physical attendance.
_Avoid_: Attended action, permanent supervision

**Printer snapshot**:
The latest set of facts observed about a printer, including when each fact was observed. A snapshot may contain stale or unknown facts and does not by itself prove the printer's current physical state.
_Avoid_: Live state, current state
