# Project Instructions

## Printer safety

- **Always confirm the human is present before operating the 3D printer
  directly.** "Operating directly" means any command that can cause the
  printer to move, heat, start/pause/resume/stop a job, or otherwise act
  physically — over MQTT, PPPP, serial, or the web UI. This includes live
  test suites gated on `ANKERCTL_TEST_ALLOW_*`.

  Why: these actions have real physical consequences (heat, motion, fire risk)
  and can wedge the firmware command queue, requiring a physical power cycle.

  How to apply: before issuing such a command, get explicit confirmation in the
  current session that the operator is at the printer with the bed clear and a
  safe toolhead path. Read-only observation (e.g. `ankerctl mqtt monitor`,
  capturing existing traffic) does not require this, but starting a job or
  sending motion/heat/control does.
