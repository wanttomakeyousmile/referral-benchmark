# Timing and scenario rules

This document specifies simulated time progression, event triggers, and task-specific scenario rules.

A new logical call advances simulated time by 60 seconds. Replay of the same gateway call identifier is distinct from a new logical call. Events may run before or after an operation. A rejected operation need not undo an environmental change that occurred before its prerequisite checks.

In RR_016/RR_018, invalidation occurs after slot discovery or before booking, whichever happens first, and fires once. Events triggered before an operation require arguments that satisfy the schema, but can still occur before the operation rejects an invalid identifier. Booking checks use the resulting state. These tasks have no separate required-event success gate.

RR_003/RR_019/RR_020 retain event-occurrence requirements. RR_019/RR_020 also require fresh post-change evidence, including the specified refreshed observations.

RR_003 allows early rerouting, and the complete-submission trigger still fires. RR_017's disruption applies only to an attempt on the original slot, so direct booking of a valid backup is allowed. RR_012 must preserve its existing valid appointment. Interpret outcomes with actual path and event exposure rather than assuming every successful run encounters each intended obstacle.

Use this description alongside tasks/EVALUATION_SPECIFICATIONS.md, the versioned task definitions, public policies, and the existing grader verification report. The evaluator retains hidden event definitions; this document does not change the agent/evaluator boundary.
