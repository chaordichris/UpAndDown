"""
Initialize the database: create all tables.

Usage:
    python scripts/init_db.py
    python scripts/init_db.py --url sqlite:///./data/db/test.db
"""

import argparse
import sys
from pathlib import Path

# Allow running as a script from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the golf-trading database.")
    parser.add_argument("--url", default=None, help="Override DATABASE_URL")
    args = parser.parse_args()

    print("Initializing database...")
    init_db(database_url=args.url)
    print("Done. All tables created (or already existed).")


if __name__ == "__main__":
    main()
