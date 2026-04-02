import sqlite3
import json
import os
from datetime import datetime

DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.db")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    # Create cases table
    c.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            corno TEXT,
            accused TEXT,
            complaintant TEXT,
            prosecution TEXT,
            court TEXT,
            judge TEXT,
            district TEXT,
            chargesheet TEXT,
            plea TEXT,
            defense TEXT,
            sentence_issued TEXT,
            date TEXT,
            filing_date DATE,
            summary TEXT
        )
    """)

    # Create indexes for performance
    c.execute("CREATE INDEX IF NOT EXISTS idx_cases_district ON cases(district)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cases_judge ON cases(judge)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cases_court ON cases(court)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_cases_filing_date ON cases(filing_date DESC, id DESC)"
    )

    # Check if empty
    c.execute("SELECT count(*) FROM cases")
    if c.fetchone()[0] == 0:
        print("Initializing database with data from cases.json...")
        load_initial_data(c)

    conn.commit()
    conn.close()


def load_initial_data(cursor):
    json_path = os.path.join(DATA_DIR, "cases.json")
    if not os.path.exists(json_path):
        print("cases.json not found.")
        return

    try:
        with open(json_path, "r") as f:
            data = json.load(f)

        for item in data:
            # Handle alias
            complaintant = item.get("complaintant") or item.get("complaininat")

            # Parse date for sorting
            date_str = item.get("date", "")
            try:
                filing_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except:
                filing_date = None

            cursor.execute(
                """
                INSERT OR IGNORE INTO cases (
                    corno, accused, complaintant, prosecution, court, judge, district, 
                    chargesheet, plea, defense, sentence_issued, date, filing_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    item.get("corno"),
                    item.get("accused"),
                    complaintant,
                    item.get("prosecution"),
                    item.get("court"),
                    item.get("judge"),
                    item.get("district"),
                    item.get("chargesheet"),
                    item.get("plea"),
                    item.get("defense"),
                    item.get("sentence_issued"),
                    date_str,
                    filing_date,
                ),
            )
    except Exception as e:
        print(f"Error loading initial data: {e}")


def parse_date(date_str):
    if not date_str:
        return None

    s = date_str.strip()

    # Try various formats
    formats = [
        "%Y-%m-%d",  # 2025-10-09
        "%d-%m-%Y",  # 03-10-2025
        "%d.%m.%Y",  # 03.10.2025
        "%d/%m/%Y",  # 03/10/2025
        "%d/%m/%y",  # 03/10/25
        "%Y/%m/%d",  # 2025/10/09
        "%d %B, %Y",  # 30th December, 2025 (need preprocessing first really, but strptime handles %B)
        "%B %d, %Y",  # February 15, 2024
    ]

    # Pre-cleaning for "nth", "st", "nd", "rd"
    # "30th December, 2025" -> "30 December, 2025"
    s_clean = s
    for suffix in ["st", "nd", "rd", "th"]:
        # valid text date might contain 'th' in month name? No. "August" has 'st'.. wait.
        # "August" ends in st? No. "August" -> "Augu". No.
        # Be careful. only replace if preceded by digit.
        import re

        s_clean = re.sub(r"(\d+)" + suffix, r"\1", s_clean)

    for fmt in formats:
        try:
            d = datetime.strptime(s_clean, fmt).date()
            # Basic validation: Year shouldn't be too far in future
            if d.year > datetime.now().year + 1:
                continue  # Likely OCR error (e.g. 2095)
            return d
        except ValueError:
            try:
                d = datetime.strptime(s, fmt).date()  # Try original too
                if d.year > datetime.now().year + 1:
                    continue
                return d
            except ValueError:
                continue

    # Handle verbose format: "Thursday, this the 09" day of October, 2025."
    try:
        # Lowercase for easier matching
        lower_s = s.lower()

        # Remove ordinal suffixes st, nd, rd, th
        import re

        clean_s = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", lower_s)

        # Remove common words
        clean_s = (
            clean_s.replace("day of", "")
            .replace("on this", "")
            .replace(",", " ")
            .replace("  ", " ")
        )

        # Now we might have: "6 2026 tuesday january" or "friday 5 december 2025"
        # Let's try to extract Day, Month, Year using regex

        # Find 4 digit year
        year_match = re.search(r"\b(20\d{2})\b", clean_s)
        year = year_match.group(1) if year_match else None

        # Find Month (text)
        months = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "sept": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        month = None
        for m_name, m_val in months.items():
            if m_name in clean_s:
                month = m_val
                break

        # Find Day (1 or 2 digits)
        day_match = re.search(r"\b([1-9]|[12]\d|3[01])\b", clean_s)
        day = day_match.group(1) if day_match else None

        if year and month and day:
            d = datetime(int(year), month, int(day)).date()
            if d.year > datetime.now().year + 1:
                return None
            return d

    except Exception as e:
        pass

    return None


def normalize_district(district_name):
    if not district_name:
        return "Unknown"

    d = district_name.strip().lower()

    # Ranga Reddy variations - MERGE ALL
    # "r r" - spaces matter. "r r" is in "r r"
    if any(
        x in d
        for x in [
            "ranga",
            "r.r",
            "rr",
            "r r",
            "r. r",
            "cyberabad",
            "raidurgam",
            "maheshwar",
            "l.b",
            "rajendranagar",
            "ibrahimpatnam",
            "alkapoor",
            "serilingampally",
        ]
    ):
        # "maheshwar" covers "maheshwaram" and "maheshwar"
        return "Ranga Reddy"

    # Skip Lucknow (not in Telangana)
    if "lucknow" in d:
        return None

    # Nalgonda — merge Yadadri Bhuvanagiri & Miryalaguda
    if "nalgonda" in d or "miryalaguda" in d or "yadadri" in d or "bhongir" in d:
        return "Nalgonda"

    # Mahabubnagar — merge Nagarkurnool & Wanaparthy & Jogulamba Gadwal
    if (
        "mahabubnagar" in d
        or "nagarkurnool" in d
        or "wanaparthy" in d
        or "jogulamba" in d
        or "gadwal" in d
    ):
        return "Mahabubnagar"

    # Nizamabad — merge Pali & Ramareddy & Dichpally & Kamareddy
    if (
        "nizamabad" in d
        or "pali" in d
        or "ramareddy" in d
        or "dichpally" in d
        or "kamareddy" in d
        or "yellareddy" in d
    ):
        return "Nizamabad"

    # Adilabad
    if "adilabad" in d:
        return "Adilabad"

    # Karimnagar
    if "karimnagar" in d:
        return "Karimnagar"

    # Khammam — merge Bhadradri Kothagudem
    if "khammam" in d or "bhadradri" in d:
        return "Khammam"

    # Warangal
    if "warangal" in d or "hanamkonda" in d:
        return "Warangal"

    # Medak
    if "sangareddy" in d:
        return "Sangareddy"
    if "siddipet" in d:
        return "Siddipet"
    if "medak" in d:
        return "Medak"

    # Hyderbad
    if "hyderabad" in d or "secunderabad" in d:
        return "Hyderabad"

    # Medchal
    if "medchal" in d or "malkajgiri" in d or "kukatpally" in d:
        return "Medchal-Malkajgiri"

    # Vikarabad (seen in some datasets, checking if relevant or default to Unknown/Raw)
    if "vikarabad" in d:
        return "Vikarabad"

    # Cleaning: Removing "District", "Dist", trailing "."
    clean = d.replace("district", "").replace("dist", "").replace(".", "").strip()

    if clean == "r r":
        return "Ranga Reddy"

    # Check for empty brackets or noise
    if not clean or clean in [
        "not mentioned",
        "not specified",
        "unknown",
        "[]",
        "[district]",
        "not provided",
        "not specified in the provided text",
    ]:
        return "Unknown"

    return clean.title()


def clean_text(text):
    if not text:
        return ""
    if isinstance(text, list):
        return ", ".join(str(item) for item in text)
    return str(text).strip()


def load_from_json(data):
    conn = get_db_connection()
    c = conn.cursor()

    # Ensure summary column exists (migration for existing DB)
    try:
        c.execute("ALTER TABLE cases ADD COLUMN summary TEXT")
    except sqlite3.OperationalError:
        pass  # Column likely exists

    try:
        count = 0
        items_to_process = []

        if isinstance(data, list):
            items_to_process = data
        elif isinstance(data, dict):
            # Check if it's the new single-item format with metadata
            if "metadata" in data:
                # Transform to flat structure
                meta = data["metadata"]
                item = {
                    "corno": meta.get("case_number"),
                    "accused": meta.get("accused_name"),
                    "complaintant": meta.get("complaintant"),
                    "prosecution": meta.get("prosecution_advocate"),
                    "court": meta.get("court"),
                    "judge": meta.get("judge"),
                    "district": meta.get("district"),
                    "chargesheet": meta.get("charges"),
                    "plea": meta.get("accused_plea"),
                    "defense": meta.get("defense_advocate"),
                    "sentence_issued": meta.get("sentence_issued"),
                    "date": meta.get("date_of_judgment"),
                    "summary": data.get("summary"),
                }
                items_to_process = [item]
            else:
                items_to_process = [data]  # Fallback for single flat object

        for item in items_to_process:
            # Skip placeholder case numbers
            corno = clean_text(item.get("corno"))
            if corno and corno.startswith("[") and corno.endswith("]"):
                continue

            # Handle alias
            complaintant = item.get("complaintant") or item.get("complaininat")

            # Parse date for sorting
            date_str = item.get("date", "")
            filing_date = parse_date(date_str)

            # Normalize District
            raw_district = item.get("district", "")
            district = normalize_district(raw_district)

            # Skip if district is None (e.g. Lucknow)
            if district is None:
                continue

            c.execute(
                """
                INSERT INTO cases (
                    corno, accused, complaintant, prosecution, court, judge, district, 
                    chargesheet, plea, defense, sentence_issued, date, filing_date, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    clean_text(item.get("corno")),
                    clean_text(item.get("accused")),
                    clean_text(complaintant),
                    clean_text(item.get("prosecution")),
                    clean_text(item.get("court")),
                    clean_text(item.get("judge")),
                    district,
                    clean_text(item.get("chargesheet")),
                    clean_text(item.get("plea")),
                    clean_text(item.get("defense")),
                    clean_text(item.get("sentence_issued")),
                    clean_text(date_str),
                    filing_date,
                    clean_text(item.get("summary")),
                ),
            )
            if c.rowcount > 0:
                count += 1
        conn.commit()
        return count
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
