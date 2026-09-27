# /behavior-review — Behavior Review slash command
#
# Activates the behavior-review mode and begins a guided review session.
# Usage: /behavior-review
#
# This command is registered automatically by Bob IDE because
# .bob/custom_modes.yaml defines a mode with slug: behavior-review.
# This file provides the initial context for the session.

## Starting a Behavior Review

Ask the developer for the two refs if they have not given them:

> "Ready to start a behavior review. Please give me:
> 1. The **base ref** — the branch, tag or commit to compare against (for example `main`)
> 2. The **head ref** — the branch or commit to review (for example your feature branch or `HEAD`)
>
> I'll run the analysis and walk you through anything it finds."

Then run the review and follow the workflow in the mode's customInstructions:

    bobreviewer run --before <base_ref> --after <head_ref>

The command prints the run folder it saved under `.bobreviewer/runs/<run_id>/`. Read
`evidence.json` from there.

Every rule in the mode applies: only real process output counts as evidence, an unknown or
missing probe is never treated as safe, and the developer — not you — decides whether a
difference was intended.
