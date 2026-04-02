#!/usr/bin/env python3
"""CLI tool to preview and delete rows from cases.db by row ID."""

import sqlite3
import os
import sys
import textwrap

DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.db")


def get_connection():
    if not os.path.exists(DB_NAME):
        print(f"Error: Database not found at {DB_NAME}")
        sys.exit(1)
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def preview_row(conn, row_id):
    """Display all columns for a given row ID."""
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (row_id,)).fetchone()
    if not row:
        print(f"\n  No record found with id = {row_id}")
        return None

    print(f"\n{'=' * 70}")
    print(f"  RECORD ID: {row['id']}")
    print(f"{'=' * 70}")
    cols = row.keys()
    for col in cols:
        val = row[col]
        if val and len(str(val)) > 80:
            val = textwrap.fill(
                str(val), width=70, initial_indent="    ", subsequent_indent="    "
            )
            print(f"  {col}:")
            print(val)
        else:
            print(f"  {col}: {val}")
    print(f"{'=' * 70}")
    return row


def delete_row(conn, row_id):
    """Delete a row after preview and confirmation."""
    row = preview_row(conn, row_id)
    if row is None:
        return

    confirm = input(f"\n  Delete this record (id={row_id})? [y/N]: ").strip().lower()
    if confirm == "y":
        conn.execute("DELETE FROM cases WHERE id = ?", (row_id,))
        conn.commit()
        print(f"  ✓ Record {row_id} deleted.")
    else:
        print("  Cancelled.")


def show_stats(conn):
    """Show basic DB stats."""
    total = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    print(f"\n  Total records: {total}")
    print(f"  ID range: ", end="")
    r = conn.execute("SELECT MIN(id), MAX(id) FROM cases").fetchone()
    print(f"{r[0]} - {r[1]}")


def main():
    conn = get_connection()
    print(f"\n  cases.db CLI Manager")
    print(f"  Database: {DB_NAME}")
    show_stats(conn)

    print(f"\n  Commands:")
    print(f"    <number>   - Preview a record by ID")
    print(f"    d <number> - Delete a record by ID (with preview + confirmation)")
    print(f"    stats      - Show DB stats")
    print(f"    q          - Quit\n")

    while True:
        try:
            cmd = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Bye!")
            break

        if not cmd:
            continue

        if cmd.lower() == "q":
            print("  Bye!")
            break

        if cmd.lower() == "stats":
            show_stats(conn)
            continue

        if cmd.lower().startswith("d "):
            try:
                row_id = int(cmd.split()[1])
                delete_row(conn, row_id)
            except (ValueError, IndexError):
                print("  Usage: d <id>")
            continue

        # Default: preview
        try:
            row_id = int(cmd)
            preview_row(conn, row_id)
        except ValueError:
            print(f"  Unknown command: {cmd}")

    conn.close()


if __name__ == "__main__":
    main()
