import sqlite3
import os
import sys
from datetime import datetime
import re

# Add app to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import DB_NAME, parse_date

def migrate():
    print(f"Migrating dates in {DB_NAME}...")
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # helper for verbose since parse_date in database.py handles it now
    # but we need to make sure we use THAT logic.
    # We can just import parse_date from database.py!
    
    cases = c.execute("SELECT id, date, filing_date FROM cases").fetchall()
    
    updated = 0
    for case in cases:
        date_str = case['date']
        current_filing = case['filing_date']
        
        # If filing_date is missing or we want to force update (to fix previously bad parses)
        # Let's force update if date_str is present using new logic
        if date_str:
            new_date = parse_date(date_str)
            
            if new_date:
                # Update if different
                if str(new_date) != str(current_filing):
                    print(f"Updating ID {case['id']}: {date_str} -> {new_date}")
                    c.execute("UPDATE cases SET filing_date = ? WHERE id = ?", (new_date, case['id']))
                    updated += 1
            else:
                # If parse_date returns None (e.g. invalid future date), but we have a filing_date, clear it
                if current_filing:
                    print(f"Clearing invalid date for ID {case['id']}: {date_str} (was {current_filing})")
                    c.execute("UPDATE cases SET filing_date = NULL WHERE id = ?", (case['id'],))
                    updated += 1
                
    conn.commit()
    conn.close()
    print(f"Migration complete. Updated {updated} rows.")

if __name__ == "__main__":
    migrate()
