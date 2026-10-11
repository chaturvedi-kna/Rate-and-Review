import sys
from pathlib import Path

# Ensure root workspace directory is in python sys.path
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import app as application
app = application
