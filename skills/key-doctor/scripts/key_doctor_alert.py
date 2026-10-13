#!/usr/bin/env python3
"""Cron entry point: Key Doctor in --alert mode. Empty output (all healthy) means no message."""
import runpy
import sys
from pathlib import Path

sys.argv = [str(Path(__file__).with_name("key-doctor.py")), "--alert"]
runpy.run_path(sys.argv[0], run_name="__main__")
