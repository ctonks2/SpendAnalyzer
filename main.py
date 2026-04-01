"""Command-line interface entry point (DEPRECATED)

DEPRECATED: Please use `python web_app.py` instead.

The CLI is being phased out in favor of the web application which provides
a better user experience with a modern web interface.
"""
import sys

print("⚠️  WARNING: The CLI interface is DEPRECATED.")
print("    Please use the web application instead:")
print("    ")
print("    python web_app.py")
print("    ")
print("    Then open http://localhost:5000 in your browser.")
print()

from spend_analyzer.cli import run_cli


if __name__ == "__main__":
    run_cli()
