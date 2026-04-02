from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import os
import json
import glob
import re

# Try imports to support both module execution (uvicorn app.main:app) and script execution (python3 main.py)
try:
    from app.services import analytics
except ImportError:
    from services import analytics

try:
    from app.auth import (
        authenticate_user,
        get_display_name,
        change_password,
        change_username,
    )
except ImportError:
    from auth import (
        authenticate_user,
        get_display_name,
        change_password,
        change_username,
    )

app = FastAPI(title="Legal Analytics Dashboard")

# Session secret for signed cookies
# In production, set SESSION_SECRET env var to a strong random string
SESSION_SECRET = os.environ.get(
    "SESSION_SECRET", "change-me-to-a-strong-random-secret-key-in-production"
)

# Setup templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ─── Jinja2 Filters ─────────────────────────────────────────────────────────
def md_to_html(text):
    """Convert markdown bold (**text**) and line breaks to HTML."""
    if not text:
        return ""
    text = str(text)

    # 1. Convert headers (e.g., ### Heading -> <h3>Heading</h3>)
    # Ensure this happens before bold conversion to avoid nesting strong tags inside h tags prematurely if not needed,
    # but we can also just strip ** if they are in headers
    text = re.sub(
        r"^###\s+(.*)$",
        r'<h3 class="text-sm font-bold mt-4 mb-2 text-slate-800 dark:text-slate-200">\1</h3>',
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^##\s+(.*)$",
        r'<h2 class="text-base font-bold mt-5 mb-3 text-slate-800 dark:text-slate-200">\1</h2>',
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^#\s+(.*)$",
        r'<h1 class="text-lg font-bold mt-6 mb-4 text-slate-900 dark:text-white">\1</h1>',
        text,
        flags=re.MULTILINE,
    )

    # Convert horizontal rules
    text = re.sub(
        r"^---$",
        r"<hr class='my-4 border-slate-300 dark:border-slate-600'/>",
        text,
        flags=re.MULTILINE,
    )

    # Convert blockquotes
    text = re.sub(
        r"^>\s+(.*)$",
        r"<blockquote class='border-l-4 border-slate-300 dark:border-slate-600 pl-4 italic my-2 text-slate-600 dark:text-slate-400'>\1</blockquote>",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"</blockquote>\s*<blockquote[^>]*>", " ", text)

    # 2. Convert unordered lists
    # Match `- item` or `* item`
    text = re.sub(
        r"^\s*[-*]\s+(.*)$",
        r'<ul class="list-disc pl-5 my-1 text-slate-600 dark:text-slate-400"><li>\1</li></ul>',
        text,
        flags=re.MULTILINE,
    )
    # Combine adjacent </ul><ul...> into single lists
    text = re.sub(r"</ul>\s*<ul[^>]*>", "", text)

    # Convert ordered lists
    text = re.sub(
        r"^\s*\d+\.\s+(.*)$",
        r'<ol class="list-decimal pl-5 my-1 text-slate-600 dark:text-slate-400"><li>\1</li></ol>',
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"</ol>\s*<ol[^>]*>", "", text)

    # 3. Convert **bold** to <strong>
    text = re.sub(
        r"\*\*([^*]+?)\*\*",
        r"<strong class='font-semibold text-slate-700 dark:text-slate-300'>\1</strong>",
        text,
    )

    # 4. Convert \n to <br> (only for lines that aren't already wrapped in HTML blocks)
    # A simple approach is to convert remaining \n to <br>, but avoid doing it between block tags.
    # We will just do a simple replace for now.
    text = text.replace("\n", "<br>")

    # Optional cleanup for multiple <br> inside or around lists
    text = re.sub(r"<br>\s*<(ul|ol|hr|blockquote)", r"<\1", text)
    text = re.sub(r"</(ul|ol|blockquote)>\s*<br>", r"</\1>", text)
    text = re.sub(
        r"<hr[^>]*>\s*<br>",
        r"<hr class='my-4 border-slate-300 dark:border-slate-600'/>",
        text,
    )

    return text


templates.env.filters["md_to_html"] = md_to_html

# Mount static files if needed (for now we use CDNs, but good practice to have)
STATIC_DIR = os.path.join(BASE_DIR, "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Load data on startup
try:
    from app.database import init_db, get_db_connection
except ImportError:
    from database import init_db, get_db_connection

# Initialize the database
init_db()

# In a production app, we might use a lifespan event or cache this
# Deprecated: No longer loading all cases on startup
# cases = analytics.load_cases()


# ─── Authentication Middleware ───────────────────────────────────────────────
# Gates ALL routes behind login, except /login and /static assets.
# No SQL involved — uses bcrypt comparison against JSON credential store.


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Allow these paths without authentication
    public_paths = ["/login", "/static"]
    path = request.url.path

    if any(path.startswith(p) for p in public_paths):
        return await call_next(request)

    # Check if user is authenticated via session
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/login", status_code=302)

    return await call_next(request)


# SessionMiddleware MUST be added AFTER @app.middleware("http") so it becomes
# the outermost layer and populates request.session before auth_middleware runs.
app.add_middleware(
    SessionMiddleware, secret_key=SESSION_SECRET, max_age=86400
)  # 24h sessions


# ─── Auth Routes ─────────────────────────────────────────────────────────────


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # If already logged in, redirect to dashboard
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request, username: str = Form(...), password: str = Form(...)
):
    if authenticate_user(username, password):
        request.session["authenticated"] = True
        request.session["username"] = username
        request.session["display_name"] = get_display_name(username)
        return RedirectResponse(url="/", status_code=302)
    else:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid username or password. Please try again.",
            },
        )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "username": request.session.get("username", ""),
            "display_name": request.session.get("display_name", ""),
        },
    )


@app.post("/settings/change-password", response_class=HTMLResponse)
async def settings_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    username = request.session.get("username", "")
    ctx = {
        "request": request,
        "username": username,
        "display_name": request.session.get("display_name", ""),
    }

    if new_password != confirm_password:
        ctx["error"] = "New passwords do not match."
        return templates.TemplateResponse("settings.html", ctx)

    success, message = change_password(username, current_password, new_password)
    if success:
        ctx["success"] = message
    else:
        ctx["error"] = message
    return templates.TemplateResponse("settings.html", ctx)


@app.post("/settings/change-username", response_class=HTMLResponse)
async def settings_change_username(
    request: Request,
    new_username: str = Form(...),
    password: str = Form(...),
):
    current_username = request.session.get("username", "")
    ctx = {
        "request": request,
        "username": current_username,
        "display_name": request.session.get("display_name", ""),
    }

    success, message = change_username(current_username, new_username, password)
    if success:
        # Update session with new username
        request.session["username"] = new_username
        request.session["display_name"] = get_display_name(new_username)
        ctx["username"] = new_username
        ctx["display_name"] = request.session["display_name"]
        ctx["success"] = message
    else:
        ctx["error"] = message
    return templates.TemplateResponse("settings.html", ctx)


@app.get("/api/courts")
async def get_courts(district: str = None):
    conn = get_db_connection()
    if district:
        result = conn.execute(
            "SELECT DISTINCT court FROM cases WHERE district = ?", (district,)
        ).fetchall()
    else:
        result = conn.execute("SELECT DISTINCT court FROM cases").fetchall()
    conn.close()
    return {"courts": [row["court"] for row in result]}


@app.get("/", response_class=HTMLResponse)
def read_global_dashboard(request: Request, analysis_type: str = "All Outcomes"):
    stats = analytics.get_global_stats(analysis_type=analysis_type)

    return templates.TemplateResponse(
        "global.html",
        {
            "request": request,
            "analysis_type": analysis_type,  # Pass back to template to keep selection
            **stats,
        },
    )


@app.get("/records", response_class=HTMLResponse)
def read_records(
    request: Request,
    page: int = 1,
    search: str = None,
    judge: str = None,
    district: str = None,
    court: str = None,
    start_date: str = None,
    end_date: str = None,
):
    # Use the new paginated service which is database-backed
    result = analytics.get_paginated_records(
        page=page,
        search=search,
        judge=judge,
        district=district,
        court=court,
        start_date=start_date,
        end_date=end_date,
    )

    filter_description = "All Case Records"
    if judge:
        filter_description = f"Cases for Judge {judge}"
    elif district:
        filter_description = f"Cases in {district}"
    elif court:
        filter_description = f"Cases in {court}"
    elif search:
        filter_description = f"Search results for '{search}'"

    return templates.TemplateResponse(
        "records.html",
        {
            "request": request,
            "filter_description": filter_description,
            "search_query": search or "",
            "active_judge": judge or "",
            "active_district": district or "",
            "active_court": court or "",
            "start_date": start_date or "",
            "end_date": end_date or "",
            **result,
        },
    )


@app.get("/case/{corno:path}", response_class=HTMLResponse)
def read_case_details(request: Request, corno: str):
    case = analytics.get_case_by_corno(corno)

    if not case:
        # Fallback or 404
        return HTMLResponse(content="Case not found", status_code=404)

    return templates.TemplateResponse(
        "case_details.html", {"request": request, "case": case}
    )


@app.post("/api/upload")
async def upload_json(request: Request):
    try:
        data = await request.json()
        if not isinstance(data, list):
            # Try to handle file upload if sent as form data (multipart)
            # But for simplicity, let's assume client sends raw JSON body or we can handle UploadFile
            pass
    except Exception:
        pass


# Imports moved to top


@app.post("/api/upload_file")
async def upload_file(file: UploadFile = File(...)):
    try:
        content = await file.read()
        data = json.loads(content)

        # Load into DB
        try:
            from app.database import load_from_json
        except ImportError:
            from database import load_from_json

        count = load_from_json(data)

        return {"message": f"Successfully loaded {count} new records.", "count": count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/district/{district_name}", response_class=HTMLResponse)
def read_district_dashboard(request: Request, district_name: str):
    stats = analytics.get_district_stats(district_name)

    return templates.TemplateResponse("district.html", {"request": request, **stats})


@app.get("/court/{court_name}", response_class=HTMLResponse)
def read_court_dashboard(request: Request, court_name: str):
    stats = analytics.get_court_stats(court_name)

    return templates.TemplateResponse("court.html", {"request": request, **stats})


@app.get("/judge/{judge_name}", response_class=HTMLResponse)
def read_judge_dashboard(request: Request, judge_name: str):
    stats = analytics.get_judge_stats(judge_name)

    # Handle simple decoding if passed from URL encoded
    # judge_name usually works fine with FastAPI path params but just in case

    return templates.TemplateResponse("judge.html", {"request": request, **stats})


# ─── Analysis Documents helpers ──────────────────────────────────────────────

ANALYSIS_DIR = os.path.join(BASE_DIR, "analysis_documents")
NPA_ANALYSIS_DIR = os.path.join(BASE_DIR, "npa_analysis_documents")
V2_ANALYSIS_DIR = os.path.join(BASE_DIR, "v2")
V3_ANALYSIS_DIR = os.path.join(BASE_DIR, "v3")


def strip_code_fences(text: str) -> str:
    """Remove ```markdown ... ``` wrappers, heading lines, and horizontal rules."""
    if not text:
        return text
    # Remove code fence lines
    text = re.sub(r"^\s*```\w*\s*$", "", text, flags=re.MULTILINE)
    # Remove heading lines like "# Metadata Extraction"
    text = re.sub(r"^\s*#+ .*$", "", text, flags=re.MULTILINE)
    # Remove horizontal rules
    text = re.sub(r"^\s*---+\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def strip_bold(text: str) -> str:
    """Remove ** markdown bold markers from text."""
    return re.sub(r"\*\*([^*]*?)\*\*", r"\1", text) if text else text


def parse_markdown_table(md_table: str) -> list[dict]:
    """Convert a markdown table string into a list of dicts.
    Handles code fences, bold markers, and vertical Field/Value format."""
    if not md_table or not md_table.strip():
        return []

    # Strip code fences and headings
    cleaned = strip_code_fences(md_table)
    if not cleaned:
        return []

    lines = [l.strip() for l in cleaned.split("\n") if l.strip()]  # noqa: E741
    # Need at least header + separator + 1 row
    # Determine table lines by preserving only lines starting with |
    table_lines = [line for line in lines if line.startswith("|")]
    if len(table_lines) < 3:
        return []

    headers = [
        strip_bold(h.strip()).replace(":", "")
        for h in table_lines[0].strip("|").split("|")
    ]

    rows = []
    # Skip separator line at index 1
    for line in table_lines[2:]:
        # We purposely do not strip bold markup off column values so the UI displays them.
        cols = [c.strip() for c in line.strip("|").split("|")]
        row_dict = {}
        for i, header in enumerate(headers):
            clean_header = header.strip()
            val = cols[i] if i < len(cols) else ""
            row_dict[clean_header] = val
        rows.append(row_dict)

    if not rows:
        return []

    # Heuristic to check if this is a VERTICAL meta table (Field, Value pairs)
    if len(headers) >= 2:
        field_header = headers[0].lower().strip()
        if field_header in ["field", "metadata field"]:
            mapped_rows = []
            mapped_dict = {}
            for r in rows:
                keys = list(r.keys())
                if len(keys) >= 2:
                    field_name = r[keys[0]].lower().strip()
                    field_val = r[keys[1]]
                    mapped_dict[field_name] = field_val
            if mapped_dict:
                mapped_rows.append(mapped_dict)
            return mapped_rows

    return rows


def normalize_metadata(raw: dict) -> dict:
    """Normalize metadata keys so templates always get consistent fields."""
    out = {}
    for key, val in raw.items():
        # Strip bold markers from both key and value
        key_clean = strip_bold(key)
        val_clean = strip_bold(val)
        lk = key_clean.lower().strip()
        if "full court" in lk:
            out["court"] = val_clean
        elif lk == "presiding judges" or "presiding" in lk:
            out["judge"] = val_clean
        elif "case number" in lk or "citation" in lk:
            out["case_number"] = val_clean
        elif "parties" in lk:
            out["parties"] = val_clean
        elif "date" in lk:
            # Handle various date formats:
            # "Date of Judgement (ISO + Natural Text)": "2025-12-15 (Monday, 15th December 2025)"
            # "Date of Judgement": "ISO: 2025-12-15<br>Natural Text: 15th day of December, 2025"
            # "date" with "iso" and "natural" in the key
            if "iso" in lk and "natural" in lk:
                # Combined field header like "Date of Judgement (ISO + Natural Text)"
                # Value might be "2025-12-15 (Monday, 15th December 2025)"
                paren_match = re.match(r"([\d-]+)\s*\((.+)\)", val_clean)
                plus_match = re.match(r"(.+?)\s*\+\s*(.+)", val_clean)
                if paren_match:
                    out["date_iso"] = paren_match.group(1).strip()
                    out["date_natural"] = paren_match.group(2).strip()
                elif plus_match:
                    out["date_iso"] = plus_match.group(1).strip()
                    out["date_natural"] = plus_match.group(2).strip()
                else:
                    out["date_natural"] = val_clean
            elif "natural" in lk:
                out["date_natural"] = val_clean
            elif "iso" in lk:
                out["date_iso"] = val_clean
            else:
                # Generic "Date of Judgement" field
                # Check if value contains ISO: and Natural Text: sub-fields
                iso_match = re.search(r"ISO:\s*([\d-]+)", val_clean)
                nat_match = re.search(
                    r"Natural\s*Text:\s*(.+?)(?:<br>|$)", val_clean, re.IGNORECASE
                )
                paren_match = re.match(r"([\d-]+)\s*\((.+)\)", val_clean)
                if iso_match:
                    out["date_iso"] = iso_match.group(1).strip()
                if nat_match:
                    out["date_natural"] = nat_match.group(1).strip()
                elif paren_match:
                    out["date_iso"] = paren_match.group(1).strip()
                    out["date_natural"] = paren_match.group(2).strip()
                elif not iso_match:
                    out["date_natural"] = val_clean
    return out


def fallback_metadata_from_content(
    legal_summary: str, timeline_content: str = ""
) -> dict:
    """Extract metadata from legal summary text when metadata table is empty."""
    meta = {}
    if not legal_summary:
        return meta

    # Try to extract court name — patterns like "heard by the <court name> in/at/on"
    court_match = re.search(
        r"(?:heard by the|before the|in the court of|presided over by)\s+(.+?)(?:\s+(?:on|in|at)\s+\d|\.\s)",
        legal_summary,
        re.IGNORECASE,
    )
    if court_match:
        meta["court"] = court_match.group(1).strip().rstrip(",.")

    # Try to extract case number — patterns like "SC.No.X of YYYY" or "Cr.No.X/YYYY"
    case_match = re.search(
        r"((?:Spl\.)?(?:S\.?C\.?|SC|Cr|CC|Crl\.?M\.?A)[\s.]*No\.?\s*[\d/]+\s*(?:of\s*\d{4})?)",
        legal_summary,
        re.IGNORECASE,
    )
    if case_match:
        meta["case_number"] = case_match.group(1).strip()

    # Try to extract date from timeline if available
    if timeline_content:
        # Look for Judgment Date in timeline
        judgment_match = re.search(
            r"\*\*([^*]+)\*\*.*?Judgment",
            timeline_content,
            re.IGNORECASE,
        )
        if judgment_match:
            meta["date_natural"] = judgment_match.group(1).strip()

    # Try to extract parties — "State of X against/vs Y" or "X vs Y"
    parties_match = re.search(
        r"(State\s+of\s+\w+)\s+(?:against|vs\.?|versus)\s+(?:the\s+accused,?\s*(?:identified as\s+)?)?([A-Z][a-zA-Z\s.]+?)(?:,|\.\s|\s+a\s+\d)",
        legal_summary,
    )
    if parties_match:
        meta["parties"] = (
            f"{parties_match.group(1).strip()} vs {parties_match.group(2).strip()}"
        )

    return meta


def parse_markdown_sections(md_text: str) -> dict:
    """Parse sections from markdown text into a dictionary compatible with the old JSON format."""
    sections = {}

    # Split the document by '## <Section Title>'
    parts = re.split(r"^##\s+(.*)", md_text, flags=re.MULTILINE)

    # parts[0] is everything before the first '## ', typically header and *Processed on*
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        content = parts[i + 1].strip()

        # Remove trailing horizontal rules from the content
        content = re.sub(r"\n*---+\s*$", "", content).strip()

        sec_data = {"content": content}

        if "Investigation Quality Audit" in title:
            # Extract severity score from blockquote: > **Lapse Severity Score: 7/10 (🟠 SEVERE)**
            score_match = re.search(
                r">\s*\*\*[a-zA-Z\s]*Score:\s*(\d+)(?:/10)?.*?\*\*",
                content,
                re.IGNORECASE,
            )
            if score_match:
                sec_data["severity_score"] = int(score_match.group(1))

            # Extract justification from blockquote
            just_match = re.search(
                r">\s*\*\*Justification:\*\*\s*(.*?)(?=\n|$)", content
            )
            if just_match:
                sec_data["score_justification"] = just_match.group(1).strip()

            # Clean up the blockquotes from the content so the sub-section parser runs cleanly
            content = re.sub(r"^>.*$", "", content, flags=re.MULTILINE)
            sec_data["content"] = content.strip()

        sections[title] = sec_data

    return sections


def extract_outcome_from_filename(filename: str, legal_summary: str = "") -> str:
    """Get case outcome from filename prefix, falling back to content analysis."""
    upper = filename.upper()
    if upper.startswith("ACQUITTED"):
        return "Acquitted"
    elif upper.startswith("CONVICTED") or upper.startswith("CONVICTION"):
        return "Convicted"
    # Fallback: parse from legal summary content
    if legal_summary:
        lower = legal_summary.lower()
        if any(
            kw in lower
            for kw in [
                "found guilty",
                "convicted",
                "guilty of all charges",
                "conviction",
            ]
        ):
            return "Convicted"
        if any(kw in lower for kw in ["acquitted", "acquittal", "not guilty"]):
            return "Acquitted"
    return "Unknown"


def load_json_analyses(
    directory: str, source_label: str, slug_prefix: str
) -> list[dict]:
    """Scan a directory for .json analysis files and return summary dicts."""
    results = []
    json_files = sorted(glob.glob(os.path.join(directory, "*.json")))

    for fpath in json_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        fname = os.path.basename(fpath)
        stem = os.path.splitext(fname)[0]  # e.g. "1" or "ACQUITTED_...analysis"
        slug = f"{slug_prefix}_{stem}"

        file_name = data.get("file_name", fname)
        processed_on = data.get("processed_on", "")
        sections = data.get("sections", {})

        if "metadata" in data and "sections" not in data:
            # It's a V3 JSON file format
            v3_meta = data.get("metadata", {})
            court = v3_meta.get("full_court_name", "")
            date_val = v3_meta.get("date_of_judgement", "")
            case_number = v3_meta.get("case_number_citations", "")
            
            judges_raw = v3_meta.get("presiding_judges", [])
            judge = ", ".join(judges_raw) if isinstance(judges_raw, list) else str(judges_raw)
            
            parties_obj = v3_meta.get("parties", {})
            parties = ""
            if isinstance(parties_obj, dict):
                pet = parties_obj.get("petitioner_appellant", "")
                res = parties_obj.get("respondent", "")
                if pet and res:
                    parties = f"{pet} vs {res}"
            
            summary_obj = data.get("summary", {})
            legal_summary = summary_obj.get("introduction", "") + " " + summary_obj.get("prosecution_plaintiffs_case", "")
            summary_snippet = (legal_summary[:200] + "...") if len(legal_summary) > 200 else legal_summary
            
            v3_class = data.get("classification", {})
            v3_keywords = [k.lower() for k in v3_class.get("keywords", [])] if isinstance(v3_class.get("keywords"), list) else []
            if any(k in v3_keywords for k in ["acquittal", "acquitted"]):
                outcome = "Acquitted"
            elif any(k in v3_keywords for k in ["conviction", "convicted"]):
                outcome = "Convicted"
            else:
                legal_summary_full = " ".join(str(v) for v in summary_obj.values())
                outcome = extract_outcome_from_filename(file_name, legal_summary_full)
            
            severity = None
            lapses = data.get("lapses", {})
            if "severity" in lapses and isinstance(lapses["severity"], dict):
                sev_score = lapses["severity"].get("score")
                if sev_score is not None:
                    try:
                        severity = int(sev_score)
                    except ValueError:
                        pass
                        
            results.append({
                "slug": slug,
                "filename": file_name,
                "processed_on": processed_on,
                "outcome": outcome,
                "court": court,
                "judge": judge,
                "date": date_val,
                "case_number": case_number,
                "parties": parties,
                "severity_score": severity,
                "summary_snippet": summary_snippet,
                "source": source_label,
            })
            continue

        # Legal summary
        legal_sec = sections.get(
            "Comprehensive Legal Summary", sections.get("Judgment at a Glance", {})
        )
        legal_summary = (
            legal_sec.get("content", "") if isinstance(legal_sec, dict) else ""
        )

        outcome = extract_outcome_from_filename(file_name, legal_summary)

        # Metadata
        meta_sec = sections.get("Metadata Extraction", {})
        meta_content = meta_sec.get("content", "") if isinstance(meta_sec, dict) else ""
        meta_rows = parse_markdown_table(meta_content)
        meta_raw = meta_rows[0] if meta_rows else {}
        meta = normalize_metadata(meta_raw)
        if not meta:
            timeline_raw = sections.get("Chronological Event Timeline", {})
            timeline_content = (
                timeline_raw.get("content", "")
                if isinstance(timeline_raw, dict)
                else ""
            )
            meta = fallback_metadata_from_content(legal_summary, timeline_content)

        # Severity
        audit = sections.get("Investigation Quality Audit", {})
        severity = None
        if isinstance(audit, dict):
            severity = audit.get("severity_score", None)
            audit_content = audit.get("content", "")
            if audit_content:
                # Override with Overall Lapse Severity Score if present
                overall_match = re.search(
                    r"Overall Lapse Severity Score.*?\n\s*\*\*Score:\s*(\d+)",
                    audit_content,
                    re.IGNORECASE | re.DOTALL,
                )
                if overall_match:
                    severity = int(overall_match.group(1))
                else:
                    lapse_match = re.search(
                        r"Lapse Severity Score:\s*(?:\*\*)?(\d+)",
                        audit_content,
                        re.IGNORECASE,
                    )
                    if lapse_match:
                        severity = int(lapse_match.group(1))
                    elif severity is None:
                        all_scores = re.findall(
                            r"(?:^|\n)[^\n]*?Score:\s*(?:\*\*)?(\d+)",
                            audit_content,
                            re.IGNORECASE,
                        )
                        if all_scores:
                            severity = int(all_scores[-1])

        summary_snippet = (
            legal_summary[:200] + "..." if len(legal_summary) > 200 else legal_summary
        )

        results.append(
            {
                "slug": slug,
                "filename": file_name,
                "processed_on": processed_on,
                "outcome": outcome,
                "court": meta.get("court", ""),
                "judge": meta.get("judge", ""),
                "date": meta.get("date_natural", meta.get("date_iso", "")),
                "case_number": meta.get("case_number", ""),
                "parties": meta.get("parties", ""),
                "severity_score": severity,
                "summary_snippet": summary_snippet,
                "source": source_label,
            }
        )

    return results


def load_analysis_list() -> dict:
    """Scan analysis_documents/, npa_analysis_documents/, and v2/ and return summary data."""
    analyses = []
    severity_scores = []
    outcomes = {"Acquitted": 0, "Convicted": 0, "Unknown": 0}

    # ── 1. Markdown files from analysis_documents/ ──
    md_files = sorted(glob.glob(os.path.join(ANALYSIS_DIR, "*_analysis.md")))

    for fpath in md_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                md_text = f.read()
        except Exception:
            continue

        fname = os.path.basename(fpath)
        slug = fname.replace("_analysis.md", "")

        # Extract processed_on from the top
        processed_on = ""
        po_match = re.search(r"\*Processed on:\s+(.*?)\*", md_text)
        if po_match:
            processed_on = po_match.group(1).strip()

        sections = parse_markdown_sections(md_text)

        # Legal summary might be under different titles
        legal_sec = sections.get(
            "Judgment at a Glance", sections.get("Comprehensive Legal Summary", {})
        )
        legal_summary = legal_sec.get("content", "")

        outcome = extract_outcome_from_filename(fname, legal_summary)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

        # Extract metadata fields from the table
        meta_content = sections.get("Metadata Extraction", {}).get("content", "")
        meta_rows = parse_markdown_table(meta_content)
        meta_raw = meta_rows[0] if meta_rows else {}
        meta = normalize_metadata(meta_raw)
        # Fallback: extract metadata from legal summary when table is empty
        if not meta:
            timeline_raw = sections.get("Chronological Event Timeline", {}).get(
                "content", ""
            )
            meta = fallback_metadata_from_content(legal_summary, timeline_raw)

        # Severity score
        audit = sections.get("Investigation Quality Audit", {})
        severity = audit.get("severity_score", None)
        audit_content = audit.get("content", "") if isinstance(audit, dict) else ""
        if audit_content:
            overall_match = re.search(
                r"Overall Lapse Severity Score.*?\n\s*\*\*Score:\s*(\d+)",
                audit_content,
                re.IGNORECASE | re.DOTALL,
            )
            if overall_match:
                severity = int(overall_match.group(1))
            else:
                lapse_match = re.search(
                    r"Lapse Severity Score:\s*(?:\*\*)?(\d+)",
                    audit_content,
                    re.IGNORECASE,
                )
                if lapse_match:
                    severity = int(lapse_match.group(1))
                elif severity is None:
                    all_scores = re.findall(
                        r"(?:^|\n)[^\n]*?Score:\s*(?:\*\*)?(\d+)",
                        audit_content,
                        re.IGNORECASE,
                    )
                    if all_scores:
                        severity = int(all_scores[-1])
        if severity is not None:
            severity_scores.append(severity)

        # Legal summary snippet (first 200 chars)
        summary_snippet = (
            legal_summary[:200] + "..." if len(legal_summary) > 200 else legal_summary
        )

        analyses.append(
            {
                "slug": slug,
                "filename": fname,
                "processed_on": processed_on,
                "outcome": outcome,
                "court": meta.get("court", ""),
                "judge": meta.get("judge", ""),
                "date": meta.get("date_natural", meta.get("date_iso", "")),
                "case_number": meta.get("case_number", ""),
                "parties": meta.get("parties", ""),
                "severity_score": severity,
                "summary_snippet": summary_snippet,
                "source": "Standard",
            }
        )

    # ── 2. JSON files from analysis_documents/ ──
    std_json = load_json_analyses(ANALYSIS_DIR, "Standard", "std")
    analyses.extend(std_json)

    # ── 3. JSON files from npa_analysis_documents/ ──
    npa_json = load_json_analyses(NPA_ANALYSIS_DIR, "NPA", "npa")
    analyses.extend(npa_json)

    # ── 4. JSON files from v2/ ──
    v2_json = load_json_analyses(V2_ANALYSIS_DIR, "V2", "v2")
    analyses.extend(v2_json)

    # ── 5. JSON files from v3/ ──
    v3_json = load_json_analyses(V3_ANALYSIS_DIR, "V3", "v3")
    analyses.extend(v3_json)

    # Update outcomes & severity from all entries
    for a in std_json + npa_json + v2_json + v3_json:
        outcomes[a["outcome"]] = outcomes.get(a["outcome"], 0) + 1
        if a["severity_score"] is not None:
            severity_scores.append(a["severity_score"])

    avg_severity = (
        round(sum(severity_scores) / len(severity_scores), 1) if severity_scores else 0
    )

    return {
        "analyses": analyses,
        "total": len(analyses),
        "avg_severity": avg_severity,
        "outcomes": outcomes,
    }


def load_json_analysis_detail(fpath: str, slug: str) -> dict | None:
    """Load and parse a single JSON analysis file into the detail view format."""
    if not os.path.exists(fpath):
        return None

    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    file_name = data.get("file_name", os.path.basename(fpath))
    processed_on = data.get("processed_on", "")
    sections = data.get("sections", {})

    if "metadata" in data and "sections" not in data:
        # V3 JSON handling
        v3_meta = data.get("metadata", {})
        court = v3_meta.get("full_court_name", "")
        date_natural = v3_meta.get("date_of_judgement", "")
        case_number = v3_meta.get("case_number_citations", "")
        
        judges_raw = v3_meta.get("presiding_judges", [])
        judge = ", ".join(judges_raw) if isinstance(judges_raw, list) else str(judges_raw)
        
        parties_obj = v3_meta.get("parties", {})
        parties = ""
        if isinstance(parties_obj, dict):
            pet = parties_obj.get("petitioner_appellant", "")
            res = parties_obj.get("respondent", "")
            if pet and res:
                parties = f"{pet} vs {res}"
        
        metadata = {
            "court": court,
            "date_natural": date_natural,
            "case_number": case_number,
            "judge": judge,
            "parties": parties
        }

        # Witnesses
        v3_witnesses = data.get("principal_witnesses_and_ex_pw", [])
        witnesses = []
        for w in v3_witnesses:
            witnesses.append({
                "Designation": w.get("designation", ""),
                "Full Name": w.get("full_name", ""),
                "Role": w.get("role", ""),
                "Key Testimony": w.get("key_testimony", "")
            })

        # Legal summary
        v3_summary = data.get("summary", {})
        legal_items = []
        if isinstance(v3_summary, dict):
            for k, v in v3_summary.items():
                title = k.replace("_", " ").title()
                legal_items.append({"title": title, "content": v})

        # Extract Exhibits from prosecution case summary for V3
        prosecution_case = v3_summary.get("prosecution_plaintiffs_case", "")
        if prosecution_case:
            # Look for patterns like "Ex.P-1", "Ex.P-12", "Ex.P-1 to Ex.P-10"
            exhibit_matches = re.finditer(r"(Ex\.P-\d+)(?:\s*(?:to|and|,)\s*(Ex\.P-\d+))?", prosecution_case)
            exhibits_found = set()
            for match in exhibit_matches:
                exhibits_found.add(match.group(1))
                if match.group(2):
                    exhibits_found.add(match.group(2))
            
            # If we found exhibits, add them to the witnesses list
            if exhibits_found:
                sorted_exhibits = sorted(list(exhibits_found), key=lambda x: int(re.search(r"\d+", x).group()) if re.search(r"\d+", x) else 0)
                for ex in sorted_exhibits:
                    witnesses.append({
                        "Designation": ex,
                        "Full Name": "Exhibit Document",
                        "Role": "Evidence",
                        "Key Testimony": f"Mentioned in prosecution case summary as marked exhibit {ex}."
                    })

        # Taxonomy
        v3_class = data.get("classification", {})
        taxonomy_items = []
        if isinstance(v3_class, dict):
            for k, v in v3_class.items():
                title = k.replace("_", " ").title()
                if isinstance(v, list):
                    v = ", ".join(v)
                if k == "keywords":
                    taxonomy_items.append({"label": "Keywords", "value": v})
                elif v:
                    taxonomy_items.append({"label": title, "value": v})

        # Timeline
        v3_timeline = data.get("timeline", [])
        timeline_items = []
        for t in v3_timeline:
            date_str = t.get("date", "")
            title = t.get("title", "")
            label = f"{date_str} - {title}" if date_str else title
            detail = t.get("excerpt", "")
            if t.get("reasoning"):
                detail += f"\n\n**Reasoning**: {t.get('reasoning')}"
            timeline_items.append({"label": label, "detail": detail})
        # Audit
        v3_lapses = data.get("lapses", {})
        audit_subsections = []
        severity_score = None
        score_justification = ""
        
        if isinstance(v3_lapses, dict):
            for dept, items in v3_lapses.items():
                if dept in ["severity", "judicial_criticism", "perfect_chain_of_evidence"]:
                    continue
                if isinstance(items, list) and items:
                    dept_items = []
                    for item in items:
                        title = item.get("lapse", "")
                        detail = f"**Impact**: {item.get('impact', '')}\n\n**Reasoning**: {item.get('reasoning', '')}"
                        dept_items.append({"title": title, "detail": detail})
                    audit_subsections.append({"heading": f"{dept.title()} Lapses", "items": dept_items})
            
            if "judicial_criticism" in v3_lapses:
                audit_subsections.append({"heading": "Judicial Criticism", "items": [{"title": "", "detail": v3_lapses["judicial_criticism"]}]})
            if "perfect_chain_of_evidence" in v3_lapses:
                audit_subsections.append({"heading": "Chain of Evidence Status", "items": [{"title": "", "detail": v3_lapses["perfect_chain_of_evidence"]}]})
                
            if "severity" in v3_lapses and isinstance(v3_lapses["severity"], dict):
                sev_score = v3_lapses["severity"].get("score")
                if sev_score is not None:
                    try:
                        severity_score = int(sev_score)
                    except ValueError:
                        pass
                score_justification = v3_lapses["severity"].get("rationale", "")

        v3_keywords = [k.lower() for k in v3_class.get("keywords", [])] if isinstance(v3_class.get("keywords"), list) else []
        if any(k in v3_keywords for k in ["acquittal", "acquitted"]):
            outcome = "Acquitted"
        elif any(k in v3_keywords for k in ["conviction", "convicted"]):
            outcome = "Convicted"
        else:
            legal_summary_full = " ".join(str(v) for k, v in v3_summary.items()) if isinstance(v3_summary, dict) else ""
            outcome = extract_outcome_from_filename(file_name, legal_summary_full)
        
        # Determine source
        if slug.startswith("npa_"):
            source = "NPA"
        elif slug.startswith("v2_"):
            source = "V2"
        elif slug.startswith("v3_"):
            source = "V3"
        else:
            source = "Standard"

        return {
            "slug": slug,
            "filename": file_name,
            "processed_on": processed_on,
            "outcome": outcome,
            "metadata": metadata,
            "witnesses": witnesses,
            "legal_summary": legal_items,
            "taxonomy": taxonomy_items,
            "timeline": timeline_items,
            "severity_score": severity_score,
            "score_justification": score_justification,
            "audit_subsections": audit_subsections,
            "source": source,
        }

    # Original V1/V2 parsing logic below
    # Metadata
    meta_sec = sections.get("Metadata Extraction", {})
    meta_content = meta_sec.get("content", "") if isinstance(meta_sec, dict) else ""
    meta_rows = parse_markdown_table(meta_content)
    metadata_raw = meta_rows[0] if meta_rows else {}
    metadata = normalize_metadata(metadata_raw)

    # Legal summary
    legal_sec = sections.get(
        "Comprehensive Legal Summary", sections.get("Judgment at a Glance", {})
    )
    legal_raw = legal_sec.get("content", "") if isinstance(legal_sec, dict) else ""
    timeline_sec = sections.get("Chronological Event Timeline", {})
    timeline_raw = (
        timeline_sec.get("content", "") if isinstance(timeline_sec, dict) else ""
    )

    if not metadata:
        metadata = fallback_metadata_from_content(legal_raw, timeline_raw)

    # Witnesses
    witnesses_sec = sections.get("Principal Witnesses & Ex.PW Extraction", {})
    if not witnesses_sec:
        witnesses_sec = sections.get("Witnesses Extracted", {})
    if not witnesses_sec:
        witnesses_sec = sections.get("Principal Witnesses", {})
    witnesses_content = (
        witnesses_sec.get("content", "") if isinstance(witnesses_sec, dict) else ""
    )
    witnesses = parse_markdown_table(witnesses_content)

    # Legal summary items
    legal_items = []
    if legal_raw:
        pattern = r"(?:^|\n)(?:#{1,6}\s*)?(?:\*\*)?(\d+\.\s+(?:\*\*)?[^\n*:]+)(?:\*\*)?:?\s*(?=\n|$)"
        parts = re.split(pattern, legal_raw)

        current_title = ""
        preamble = parts[0].strip() if parts else ""
        if preamble and not re.search(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\d+\.\s+", parts[0]):
            legal_items.append({"title": "Overview", "content": preamble})

        for i in range(1, len(parts), 2):
            if i < len(parts):
                current_title = parts[i].strip()
                current_title = re.sub(r"^[\*\#]+|[\*\#]+$", "", current_title).strip()
                current_title = re.sub(r"^\d+\.\s*", "", current_title).strip()
                current_title = re.sub(r"^[\*\#]+|[\*\#]+$", "", current_title).strip()

            content = parts[i + 1].strip() if i + 1 < len(parts) else ""

            if current_title:
                legal_items.append({"title": current_title, "content": content})

        if not legal_items:
            legal_items.append({"title": "Summary", "content": legal_raw})

    # Taxonomy
    taxonomy_sec = sections.get("Taxonomy & Classification", {})
    taxonomy_content = (
        taxonomy_sec.get("content", "") if isinstance(taxonomy_sec, dict) else ""
    )
    taxonomy_items = []
    if taxonomy_content:
        # NPA Taxonomy puts everything under a single header or multiple headers.
        # We want to pass the raw string into template so `md_to_html` can format it,
        # or structure it nicely.
        # The frontend template does this:
        # {% if t.label %} <p label> {% endif %} <p value>
        # Let's just create a single item where value is the raw content so md_to_html works properly.
        taxonomy_items.append({"label": "", "value": taxonomy_content})

    # Timeline
    timeline_items = []
    if timeline_raw:
        for line in timeline_raw.strip().split("\n"):
            line = line.strip().lstrip("- ")
            if not line:
                continue
            bold_match = re.match(r"\*\*([^*]+)\*\*:\s*(.*)", line)
            if bold_match:
                timeline_items.append(
                    {
                        "label": bold_match.group(1).strip(),
                        "detail": bold_match.group(2).strip(),
                    }
                )
            else:
                timeline_items.append({"label": "", "detail": line})

    # Audit
    audit_section = sections.get("Investigation Quality Audit", {})
    audit_content = (
        audit_section.get("content", "") if isinstance(audit_section, dict) else ""
    )
    severity_score = (
        audit_section.get("severity_score", 0) if isinstance(audit_section, dict) else 0
    )
    score_justification = (
        audit_section.get("score_justification", "")
        if isinstance(audit_section, dict)
        else ""
    )

    # Always try to extract the OVERALL severity score from content body
    # because the top-level key can sometimes be a department sub-score
    if audit_content:
        # First, try to find the overall score (after "Overall Lapse Severity Score" heading)
        overall_match = re.search(
            r"Overall Lapse Severity Score.*?\n\s*\*\*Score:\s*(\d+)",
            audit_content,
            re.IGNORECASE | re.DOTALL,
        )
        if overall_match:
            severity_score = int(overall_match.group(1))
        else:
            # Try "Lapse Severity Score: N" pattern (always overrides top-level)
            lapse_match = re.search(
                r"Lapse Severity Score:\s*(?:\*\*)?(\d+)",
                audit_content,
                re.IGNORECASE,
            )
            if lapse_match:
                severity_score = int(lapse_match.group(1))
            elif not severity_score:
                # Fallback: find last "Score: N" line (the overall is usually at the end)
                all_scores = re.findall(
                    r"(?:^|\n)[^\n]*?Score:\s*(?:\*\*)?(\d+)",
                    audit_content,
                    re.IGNORECASE,
                )
                if all_scores:
                    severity_score = int(all_scores[-1])

    audit_subsections = []
    if audit_content:
        current_heading = ""
        current_items = []
        for line in audit_content.strip().split("\n"):
            original_line = line
            line = line.strip()
            if not line or line == "---":
                continue

            # Skip score line so it doesn't become a header
            if (
                re.search(r"Lapse Severity Score", line, re.IGNORECASE)
                or re.search(r"^\s*(?:\*\*)?Score:", line, re.IGNORECASE)
                or "Observations/Lapses" in line
            ):
                continue

            # Match strict markdown headings like `### Heading` or `## **1. Department Lapses**`
            heading_match = re.match(r"^#{2,4}\s+(?:\*\*)?(.*?)(?:\*\*)?:?\s*$", line)
            alt_heading_match = re.match(r"^\*\*([^*]+)\*\*:?\s*$", line)

            if alt_heading_match and (
                "Score:" in line
                or len(line) > 60
                or "Observations" in line
                or "Rationale" in line
            ):
                alt_heading_match = None

            if heading_match or alt_heading_match:
                if current_heading:
                    audit_subsections.append(
                        {"heading": current_heading, "items": current_items}
                    )
                current_heading = (
                    (
                        heading_match.group(1)
                        if heading_match
                        else alt_heading_match.group(1)
                    )
                    .strip()
                    .rstrip(":")
                )
                current_heading = re.sub(r"^\*\*|\*\*$", "", current_heading).strip()
                current_items = []
            else:
                bullet_bold_match = re.match(
                    r"^(?:-|\*|\d+\.)\s+\*\*([^*]+)\*\*:?\s*(.*)", line
                )
                if bullet_bold_match:
                    current_items.append(
                        {
                            "title": bullet_bold_match.group(1).strip(),
                            "detail": bullet_bold_match.group(2).strip(),
                        }
                    )
                else:
                    top_level_match = re.match(r"^(?:\d+\.)\s+(.*)", line)
                    if (
                        top_level_match
                        and not original_line.startswith(" ")
                        and not original_line.startswith("\t")
                    ):
                        current_items.append(
                            {"title": "", "detail": top_level_match.group(1).strip()}
                        )
                    else:
                        if current_items:
                            if current_items[-1]["detail"]:
                                current_items[-1]["detail"] += "\n" + line
                            else:
                                current_items[-1]["detail"] = line
                        else:
                            current_items.append({"title": "", "detail": line})

        if current_heading:
            audit_subsections.append(
                {"heading": current_heading, "items": current_items}
            )
        if not audit_subsections and audit_content.strip():
            audit_subsections.append(
                {
                    "heading": "Audit Summary",
                    "items": [{"title": "", "detail": audit_content.strip()}],
                }
            )

    outcome = extract_outcome_from_filename(file_name, legal_raw)
    # Determine source from slug prefix
    if slug.startswith("npa_"):
        source = "NPA"
    elif slug.startswith("v2_"):
        source = "V2"
    elif slug.startswith("v3_"):
        source = "V3"
    else:
        source = "Standard"

    return {
        "slug": slug,
        "filename": file_name,
        "processed_on": processed_on,
        "outcome": outcome,
        "metadata": metadata,
        "witnesses": witnesses,
        "legal_summary": legal_items,
        "taxonomy": taxonomy_items,
        "timeline": timeline_items,
        "severity_score": severity_score,
        "score_justification": score_justification,
        "audit_subsections": audit_subsections,
        "source": source,
    }


def load_analysis_detail(slug: str) -> dict | None:
    """Load and parse a single analysis by its slug (supports md, std JSON, and NPA JSON)."""
    # Handle NPA JSON slugs  (npa_1, npa_2, ...)
    if slug.startswith("npa_"):
        stem = slug[4:]  # remove "npa_" prefix
        fpath = os.path.join(NPA_ANALYSIS_DIR, f"{stem}.json")
        return load_json_analysis_detail(fpath, slug)

    # Handle V2 JSON slugs  (v2_1, v2_2, ...)
    if slug.startswith("v2_"):
        stem = slug[3:]  # remove "v2_" prefix
        fpath = os.path.join(V2_ANALYSIS_DIR, f"{stem}.json")
        return load_json_analysis_detail(fpath, slug)

    # Handle V3 JSON slugs  (v3_1, v3_2, ...)
    if slug.startswith("v3_"):
        stem = slug[3:]  # remove "v3_" prefix
        fpath = os.path.join(V3_ANALYSIS_DIR, f"{stem}.json")
        return load_json_analysis_detail(fpath, slug)

    # Handle Standard JSON slugs  (std_ACQUITTED_...)
    if slug.startswith("std_"):
        stem = slug[4:]  # remove "std_" prefix
        fpath = os.path.join(ANALYSIS_DIR, f"{stem}.json")
        return load_json_analysis_detail(fpath, slug)

    # Original: markdown files
    fpath = os.path.join(ANALYSIS_DIR, f"{slug}_analysis.md")
    if not os.path.exists(fpath):
        return None

    with open(fpath, "r", encoding="utf-8") as f:
        md_text = f.read()

    processed_on = ""
    po_match = re.search(r"\*Processed on:\s+(.*?)\*", md_text)
    if po_match:
        processed_on = po_match.group(1).strip()

    sections = parse_markdown_sections(md_text)

    # Parse metadata table
    meta_content = sections.get("Metadata Extraction", {}).get("content", "")
    meta_rows = parse_markdown_table(meta_content)
    metadata_raw = meta_rows[0] if meta_rows else {}
    metadata = normalize_metadata(metadata_raw)

    # Legal summary might be under different titles
    legal_sec = sections.get(
        "Judgment at a Glance", sections.get("Comprehensive Legal Summary", {})
    )
    legal_raw = legal_sec.get("content", "")
    timeline_raw = sections.get("Chronological Event Timeline", {}).get("content", "")

    # Fallback: extract metadata from content when table is empty
    if not metadata:
        metadata = fallback_metadata_from_content(legal_raw, timeline_raw)

    # Parse witnesses table
    witnesses_content = sections.get("Principal Witnesses & Ex.PW Extraction", {}).get(
        "content", ""
    )
    if not witnesses_content:
        witnesses_content = sections.get("Witnesses Extracted", {}).get("content", "")
    if not witnesses_content:
        witnesses_content = sections.get("Principal Witnesses", {}).get("content", "")

    witnesses = parse_markdown_table(witnesses_content)

    # Legal summary (split numbered items for tabbed display)
    legal_items = []
    if legal_raw:
        pattern = r"(?:^|\n)(?:#{1,6}\s*)?(?:\*\*)?(\d+\.\s+(?:\*\*)?[^\n*:]+)(?:\*\*)?:?\s*(?=\n|$)"
        parts = re.split(pattern, legal_raw)

        current_title = ""
        preamble = parts[0].strip() if parts else ""
        if preamble and not re.search(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\d+\.\s+", parts[0]):
            legal_items.append({"title": "Overview", "content": preamble})

        for i in range(1, len(parts), 2):
            if i < len(parts):
                current_title = parts[i].strip()
                current_title = re.sub(r"^[\*\#]+|[\*\#]+$", "", current_title).strip()
                current_title = re.sub(r"^\d+\.\s*", "", current_title).strip()
                current_title = re.sub(r"^[\*\#]+|[\*\#]+$", "", current_title).strip()

            content = parts[i + 1].strip() if i + 1 < len(parts) else ""

            if current_title:
                legal_items.append({"title": current_title, "content": content})

        if not legal_items:
            legal_items.append({"title": "Summary", "content": legal_raw})

    # Taxonomy
    taxonomy_content = sections.get("Taxonomy & Classification", {}).get("content", "")
    taxonomy_items = []
    if taxonomy_content:
        taxonomy_items.append({"label": "", "value": taxonomy_content})

    # Timeline
    timeline_content = sections.get("Chronological Event Timeline", {}).get(
        "content", ""
    )
    timeline_items = []
    if timeline_content:
        current_label = ""
        current_detail = []
        for line in timeline_content.strip().split("\n"):
            original_line = line
            clean_line = line.strip()
            if (
                not clean_line
                or clean_line.replace("*", "") == "Chronological Event Timeline"
            ):
                continue

            if original_line.startswith("- ") and "**" in clean_line:
                if current_label or current_detail:
                    timeline_items.append(
                        {
                            "label": current_label,
                            "detail": "\n".join(current_detail).strip(),
                        }
                    )
                bold_match = re.match(r"-\s+\*\*([^*]+)\*\*:\s*(.*)", original_line)
                if bold_match:
                    current_label = bold_match.group(1).strip()
                    detail_part = bold_match.group(2).strip()
                    current_detail = [detail_part] if detail_part else []
                else:
                    current_label = ""
                    current_detail = [original_line]
            else:
                current_detail.append(original_line)

        if current_label or current_detail:
            timeline_items.append(
                {"label": current_label, "detail": "\n".join(current_detail).strip()}
            )

    # Investigation Quality Audit
    audit_section = sections.get("Investigation Quality Audit", {})
    audit_content = audit_section.get("content", "")
    severity_score = audit_section.get("severity_score", 0)
    score_justification = audit_section.get("score_justification", "")

    # Always try to extract the OVERALL severity score from content body
    # because the top-level key can sometimes be a department sub-score
    if audit_content:
        # First, try to find the overall score (after "Overall Lapse Severity Score" heading)
        overall_match = re.search(
            r"Overall Lapse Severity Score.*?\n\s*\*\*Score:\s*(\d+)",
            audit_content,
            re.IGNORECASE | re.DOTALL,
        )
        if overall_match:
            severity_score = int(overall_match.group(1))
        else:
            # Try "Lapse Severity Score: N" pattern (always overrides top-level)
            lapse_match = re.search(
                r"Lapse Severity Score:\s*(?:\*\*)?(\d+)",
                audit_content,
                re.IGNORECASE,
            )
            if lapse_match:
                severity_score = int(lapse_match.group(1))
            elif not severity_score:
                # Fallback: find last "Score: N" line (the overall is usually at the end)
                all_scores = re.findall(
                    r"(?:^|\n)[^\n]*?Score:\s*(?:\*\*)?(\d+)",
                    audit_content,
                    re.IGNORECASE,
                )
                if all_scores:
                    severity_score = int(all_scores[-1])

    # Parse audit into sub-sections
    audit_subsections = []
    if audit_content:
        current_heading = ""
        current_items = []
        for line in audit_content.strip().split("\n"):
            original_line = line
            line = line.strip()
            if not line or line == "---":
                continue

            # Skip score line so it doesn't become a header
            if (
                re.search(r"Lapse Severity Score", line, re.IGNORECASE)
                or re.search(r"^\s*(?:\*\*)?Score:", line, re.IGNORECASE)
                or "Observations/Lapses" in line
            ):
                continue

            # Match either `### Heading` or `## **1. Lapses**` or `**Heading**: `
            heading_match = re.match(r"^#{2,4}\s+(?:\*\*)?(.*?)(?:\*\*)?:?\s*$", line)
            alt_heading_match = re.match(r"^\*\*([^*]+)\*\*:?\s*$", line)

            if alt_heading_match and (
                "Score:" in line
                or len(line) > 60
                or "Observations" in line
                or "Rationale" in line
            ):
                alt_heading_match = None

            if heading_match or alt_heading_match:
                if current_heading:
                    audit_subsections.append(
                        {"heading": current_heading, "items": current_items}
                    )
                if heading_match:
                    current_heading = heading_match.group(1).strip().rstrip(":")
                else:
                    current_heading = alt_heading_match.group(1).strip().rstrip(":")
                current_heading = re.sub(r"^\*\*|\*\*$", "", current_heading).strip()
                current_items = []
            else:
                bullet_bold_match = re.match(
                    r"^(?:-|\*|\d+\.)\s+\*\*([^*]+)\*\*:?\s*(.*)", line
                )
                if bullet_bold_match:
                    current_items.append(
                        {
                            "title": bullet_bold_match.group(1).strip(),
                            "detail": bullet_bold_match.group(2).strip(),
                        }
                    )
                else:
                    top_level_match = re.match(r"^(?:\d+\.)\s+(.*)", line)
                    if (
                        top_level_match
                        and not original_line.startswith(" ")
                        and not original_line.startswith("\t")
                    ):
                        current_items.append(
                            {"title": "", "detail": top_level_match.group(1).strip()}
                        )
                    else:
                        if current_items:
                            if current_items[-1]["detail"]:
                                current_items[-1]["detail"] += "\n" + line
                            else:
                                current_items[-1]["detail"] = line
                        else:
                            current_items.append({"title": "", "detail": line})

        if current_heading:
            audit_subsections.append(
                {"heading": current_heading, "items": current_items}
            )

        # Fallback: if no structured sub-sections are found, just use the remaining text
        if not audit_subsections and audit_content.strip():
            audit_subsections.append(
                {
                    "heading": "Audit Summary",
                    "items": [{"title": "", "detail": audit_content.strip()}],
                }
            )

    outcome = extract_outcome_from_filename(os.path.basename(fpath), legal_raw)

    return {
        "slug": slug,
        "filename": os.path.basename(fpath),
        "processed_on": processed_on,
        "outcome": outcome,
        "metadata": metadata,
        "witnesses": witnesses,
        "legal_summary": legal_items,
        "taxonomy": taxonomy_items,
        "timeline": timeline_items,
        "severity_score": severity_score,
        "score_justification": score_justification,
        "audit_subsections": audit_subsections,
        "source": "Standard",
    }


@app.get("/analyses", response_class=HTMLResponse)
async def read_analyses(request: Request):
    data = load_analysis_list()
    return templates.TemplateResponse(
        "analysis_list.html", {"request": request, **data}
    )


@app.get("/analysis/{slug}", response_class=HTMLResponse)
async def read_analysis_detail(request: Request, slug: str):
    detail = load_analysis_detail(slug)
    if not detail:
        return HTMLResponse(content="Analysis not found", status_code=404)
    return templates.TemplateResponse(
        "analysis_detail.html", {"request": request, **detail}
    )


if __name__ == "__main__":
    import uvicorn

    # Check if we can import 'app' to decide the app string
    try:
        import app.main

        app_str = "app.main:app"
    except ImportError:
        app_str = "main:app"

    # Disable reload if running as script to avoid import confusion in reload verify
    uvicorn.run(app_str, host="0.0.0.0", port=9102)
