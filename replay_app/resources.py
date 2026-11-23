"""Paths shared by source runs and the frozen Windows application."""
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
ASSETS = RESOURCE_ROOT / "assets"
