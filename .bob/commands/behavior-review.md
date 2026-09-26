# /behavior-review — Behavior Review slash command
#
# Activates the behavior-review mode and begins a guided review session.
# Usage: /behavior-review
#
# This command is registered automatically by Bob IDE because
# .bob/custom_modes.yaml defines a mode with slug: behavior-review.
# This file provides additional invocation guidance and initial context.

## Starting a Behavior Review

Read the following files before beginning:
- `PROJECT_SPEC.md` — full product specification
- `contracts/evidence.schema.json` — evidence bundle schema
- `contracts/decision.schema.json` — decision record schema
- `contracts/probe.schema.json` — probe file schema
- `handoffs/D.md` — Lane 4 handoff notes

Then ask the developer:

> "Ready to start a behavior review. Please provide:
> 1. The **base ref** (e.g., `demo-base` or a commit SHA)
> 2. The **head ref** (e.g., the branch name or commit SHA you want to review)
>
> I'll run the analysis and walk you through any differences found."

Follow the workflow defined in the behavior-review mode's customInstructions.
