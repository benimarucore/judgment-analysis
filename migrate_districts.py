import sqlite3
import os
import sys

# Add app to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import DB_NAME, normalize_district

def migrate_districts():
    print(f"Migrating districts in {DB_NAME}...")
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    cases = c.execute("SELECT id, district FROM cases").fetchall()
    
    updated = 0
    for case in cases:
        old_dist = case['district']
        
        # Apply normalization
        new_dist = normalize_district(old_dist)
        
        if old_dist != new_dist:
            print(f"Updating ID {case['id']}: '{old_dist}' -> '{new_dist}'")
            c.execute("UPDATE cases SET district = ? WHERE id = ?", (new_dist, case['id']))
            updated += 1
                
    conn.commit()
    conn.close()
    print(f"District migration complete. Updated {updated} rows.")

if __name__ == "__main__":
    migrate_districts()
