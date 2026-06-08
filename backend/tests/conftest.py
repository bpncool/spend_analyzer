import os
import pytest

# Force DATABASE_URL to be an in-memory SQLite database during test collection and run
os.environ["DATABASE_URL"] = "sqlite://"
