"""app/cli.py — Compatibility entry point delegating to bobthereviewer.cli."""
from bobthereviewer.cli import main, build_parser

if __name__ == "__main__":
    import sys
    sys.exit(main())
