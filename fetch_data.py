import json
import sys
import os
import glob

# Add current directory to path so we can import app modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from app.database import load_from_json, init_db, DB_NAME
except ImportError:
    # Fallback if run from inside app/
    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
    from database import load_from_json, init_db, DB_NAME

# Local directory containing all the summary JSON files
SUMMARY_OUTPUT_DIR = os.path.expanduser(
    "~/docling_test/ExtractionPipeline/summary_output"
)


def fetch_and_load():
    print(f"Loading data from local directory: {SUMMARY_OUTPUT_DIR}")

    if not os.path.isdir(SUMMARY_OUTPUT_DIR):
        print(f"Error: Directory not found: {SUMMARY_OUTPUT_DIR}")
        return

    # Delete existing DB for a fresh load
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        print(f"Removed existing database: {DB_NAME}")

    # Initialize fresh DB
    init_db()

    # Find all JSON files recursively
    json_files = glob.glob(
        os.path.join(SUMMARY_OUTPUT_DIR, "**", "*_summary.json"), recursive=True
    )
    print(f"Found {len(json_files)} JSON files to process.")

    total_loaded = 0
    total_files = 0
    errors = 0

    for filepath in json_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                file_content = json.load(f)

            count = load_from_json(file_content)
            total_loaded += count
            total_files += 1

            # Print progress every 100 files
            if total_files % 100 == 0:
                print(f"  Processed {total_files}/{len(json_files)} files...")

        except Exception as e:
            errors += 1
            print(f"  Error processing {os.path.basename(filepath)}: {e}")

    print(
        f"\nDone! Processed {total_files} files. Loaded {total_loaded} records into the database."
    )
    if errors:
        print(f"  ({errors} files had errors)")


if __name__ == "__main__":
    fetch_and_load()
