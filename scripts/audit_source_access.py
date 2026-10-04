#!/usr/bin/env python3
"""Compatibility entry for the installed, secret-free capability doctor.

The canonical implementation lives in sourceglint.health. JSON now uses its
versioned schema, and historical live passes are explicitly historical.
"""
from sourceglint.health import build_report, main

if __name__ == "__main__":
    raise SystemExit(main())
