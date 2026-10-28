# Live hardware completion — execution plan

2026-10-29. Development branch `hardware-read-gripper-only`, starting at merge `ab94b87` (source tree identical to reviewed `7db7438`). Current request: preserve simulation/full Fake control while live hardware defaults to observation-only. Never write arm Goal/Torque; gripper motion needs separate supervised, direction/displacement-specific approval. No Hub remote writes without explicit approval.

1. Existing SDK lifecycle/source audit and torque-preserving observation boundary; Fake lifecycle tests.
2. Explicit Live Leader selection, feedback/Precision/Capture/Observe-only loops through existing Recipe/R03; read-only hardware identity only after source and Fake checks.
3. One-shot gripper calculation/encoding and approval-bound targeted register write; no automatic Home/Reset/torque. Fake/full-axis Teleop and Policy tests; physical full-axis blocked.
4. Camera/Builder Capture, measured-q Real/Sim comparison, UI and existing Dataset/Hub connections.
5. Full regression, wheels, independent review, original preservation; report actual versus Fake/BLOCKED. Request separate approval only after reviewable preflight evidence. No motion at present.

Local evidence: `docs/evidence/hardware-read-gripper/`; original Scene/Calibration/Dataset/checkpoints/SDK are read-only. USB paths or old profile identity alone do not certify current role/motor calibration or camera placement.
