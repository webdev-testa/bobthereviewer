"""
bobthereviewer application package.

Lane ownership:
  app/decisions.py  — Lane 4 (D): decision writer, validator, history lookup
  app/report.py     — Lane 3 (C): Markdown renderer and to_web_data helper
  app/html_report.py — Lane 3 (C): static HTML generator
  app/schemas.py    — Lane 1 (A): Pydantic contracts (schema owner)
  app/snapshot.py   — Lane 1 (A): Git worktree isolation
  app/impact.py     — Lane 1 (A): AST caller analysis
  app/runner.py     — Lane 2 (B): probe and test runner
  app/cli.py        — Lane 1 (A): CLI entry points
"""
