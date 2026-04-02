from typing import List, Dict, Any, Optional
# No longer using Counter, defaultdict, or datetime here


try:
    from app.database import get_db_connection
    from app.models import Case
except ImportError:
    from database import get_db_connection
    from models import Case

# Centralized SQL logic for verdict and status to match Case model properties
VERDICT_SQL = """
CASE 
    WHEN (date IS NULL OR date = '' OR lower(date) IN ('not specified', 'not mentioned', 'unknown', 'none', 'not provided'))
         AND (sentence_issued IS NULL OR sentence_issued = '' OR lower(sentence_issued) IN ('not specified', 'not mentioned', 'unknown', 'none'))
    THEN 'Pending'
    WHEN (lower(sentence_issued) LIKE '%acquitte%' OR lower(sentence_issued) LIKE '%not guilty%') THEN 'Acquittal'
    WHEN (lower(sentence_issued) LIKE '%convict%' OR lower(sentence_issued) LIKE '%guilty%') THEN 'Conviction'
    WHEN lower(sentence_issued) LIKE '%dismiss%' THEN 'Dismissed'
    WHEN (lower(summary) LIKE '%acquittal%' OR lower(summary) LIKE '%acquitted%' OR lower(summary) LIKE '%not guilty%') THEN 'Acquittal'
    WHEN (lower(summary) LIKE '%conviction%' OR lower(summary) LIKE '%convicted%' OR lower(summary) LIKE '%guilty%') THEN 'Conviction'
    WHEN lower(summary) LIKE '%dismiss%' THEN 'Dismissed'
    ELSE 'Decided'
END
"""

IS_ACTIVE_SQL = """
CASE 
    WHEN (date IS NULL OR date = '' OR lower(date) IN ('not specified', 'not mentioned', 'unknown', 'none', 'not provided'))
         AND (sentence_issued IS NULL OR sentence_issued = '' OR lower(sentence_issued) IN ('not specified', 'not mentioned', 'unknown', 'none'))
    THEN 1
    ELSE 0
END
"""


def load_cases() -> List[Case]:
    """Deprecated: Loads all cases into memory. Use get_paginated_records for UI."""
    conn = get_db_connection()
    cases = conn.execute("SELECT * FROM cases").fetchall()
    conn.close()
    return [Case(**dict(row)) for row in cases]


def get_case_by_corno(corno: str) -> Optional[Case]:
    """Fetch a single case by its unique COR number."""
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM cases WHERE corno = ?", (corno,)).fetchone()
    conn.close()
    if row:
        return Case(**dict(row))
    return None


def get_paginated_records(
    page: int = 1,
    page_size: int = 50,
    judge: str = None,
    district: str = None,
    court: str = None,
    search: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Dict[str, Any]:
    """Fetch a slice of cases based on filters and pagination."""
    conn = get_db_connection()
    query = "SELECT * FROM cases WHERE 1=1"
    params = []

    if judge:
        query += " AND judge = ?"
        params.append(judge)
    if district:
        query += " AND district = ?"
        params.append(district)
    if court:
        query += " AND court = ?"
        params.append(court)
    if search:
        query += " AND (accused LIKE ? OR corno LIKE ? OR summary LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])
    if start_date:
        query += " AND filing_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND filing_date <= ?"
        params.append(end_date)

    # Get total count for pagination UI
    count_query = query.replace("SELECT *", "SELECT COUNT(*)")
    total_count = conn.execute(count_query, params).fetchone()[0]

    # Add sorting and pagination
    query += " ORDER BY filing_date DESC, id DESC LIMIT ? OFFSET ?"
    offset = (page - 1) * page_size
    params.extend([page_size, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()

    cases = [Case(**dict(row)) for row in rows]

    return {
        "cases": cases,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size,
    }


def get_global_stats(analysis_type: str = "All Outcomes") -> Dict[str, Any]:
    conn = get_db_connection()

    # Build base where clause
    where_clause = "1=1"
    if analysis_type == "Convictions Only":
        where_clause = f"{VERDICT_SQL} = 'Conviction'"
    elif analysis_type == "Acquittals Only":
        where_clause = f"{VERDICT_SQL} = 'Acquittal'"

    # Counts
    active_cases = conn.execute(
        f"SELECT COUNT(*) FROM cases WHERE {IS_ACTIVE_SQL} = 1 AND {where_clause}"
    ).fetchone()[0]
    total_cases = conn.execute(
        f"SELECT COUNT(*) FROM cases WHERE {where_clause}"
    ).fetchone()[0]

    # Verdicts
    verdict_rows = conn.execute(
        f"SELECT {VERDICT_SQL} as v, COUNT(*) as c FROM cases WHERE {where_clause} GROUP BY v"
    ).fetchall()
    verdict_counts = {row["v"]: row["c"] for row in verdict_rows}

    decided_pool = sum(count for v, count in verdict_counts.items() if v != "Pending")
    total_decided = decided_pool or 1

    conviction_rate = int((verdict_counts.get("Conviction", 0) / total_decided) * 100)
    acquittal_rate = int((verdict_counts.get("Acquittal", 0) / total_decided) * 100)

    # District Volumes
    # We also want the performance status per district
    district_rows = conn.execute(
        f"""
        SELECT 
            district, 
            COUNT(*) as vol,
            AVG({IS_ACTIVE_SQL}) as active_ratio,
            SUM(CASE WHEN ({VERDICT_SQL}) = 'Conviction' THEN 1 ELSE 0 END) as convictions,
            SUM(CASE WHEN ({VERDICT_SQL}) = 'Acquittal' THEN 1 ELSE 0 END) as acquittals,
            SUM(CASE WHEN ({VERDICT_SQL}) = 'Pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN ({VERDICT_SQL}) IN ('Dismissed', 'Decided') THEN 1 ELSE 0 END) as other
        FROM cases 
        WHERE {where_clause} 
        GROUP BY district
        ORDER BY vol DESC
    """
    ).fetchall()

    district_volumes = []
    max_vol = 0
    for row in district_rows:
        vol = row["vol"]
        if vol > max_vol:
            max_vol = vol
        active_ratio = row["active_ratio"] or 0
        status = "neutral"
        if active_ratio > 0.5:
            status = "lagging"
        elif active_ratio < 0.2:
            status = "efficient"

        district_volumes.append(
            {
                "name": row["district"] or "Unknown",
                "volume": row["vol"],
                "status": status,
                "active_ratio": int(active_ratio * 100),
                "convictions": row["convictions"] or 0,
                "acquittals": row["acquittals"] or 0,
                "pending": row["pending"] or 0,
                "other": row["other"] or 0,
            }
        )

    # Recent Activity
    recent_rows = conn.execute(
        f"SELECT * FROM cases WHERE {where_clause} ORDER BY filing_date DESC, id DESC LIMIT 10"
    ).fetchall()
    recent_verdicts = [Case(**dict(row)) for row in recent_rows]

    conn.close()

    return {
        "active_cases": active_cases,
        "total_cases": total_cases,
        "conviction_rate": conviction_rate,
        "acquittal_rate": acquittal_rate,
        "conviction_count": verdict_counts.get("Conviction", 0),
        "acquittal_count": verdict_counts.get("Acquittal", 0),
        "pending_count": verdict_counts.get("Pending", 0),
        "dismissed_count": verdict_counts.get("Dismissed", 0),
        "other_decided_count": verdict_counts.get("Decided", 0),
        "district_volumes": district_volumes,
        "max_district_volume": max_vol,
        "recent_verdicts": recent_verdicts,
        "verdict_distribution": [
            verdict_counts.get("Conviction", 0),
            verdict_counts.get("Acquittal", 0),
            verdict_counts.get("Pending", 0),
            verdict_counts.get("Dismissed", 0) + verdict_counts.get("Decided", 0),
        ],
    }


def get_district_stats(district_name: str) -> Dict[str, Any]:
    conn = get_db_connection()

    # Core Counts
    counts = conn.execute(
        f"SELECT COUNT(*) as total, SUM({IS_ACTIVE_SQL}) as active FROM cases WHERE district = ?",
        (district_name,),
    ).fetchone()

    total = counts["total"] or 0
    active = counts["active"] or 0

    # Verdicts for Success Rate
    verdict_rows = conn.execute(
        f"SELECT {VERDICT_SQL} as v, COUNT(*) as c FROM cases WHERE district = ? AND {IS_ACTIVE_SQL} = 0 GROUP BY v",
        (district_name,),
    ).fetchall()
    v_counts = {row["v"]: row["c"] for row in verdict_rows}
    total_closed = sum(v_counts.values()) or 1
    success_rate = int((v_counts.get("Conviction", 0) / total_closed) * 100)

    # Court Data
    court_rows = conn.execute(
        f"SELECT court, COUNT(*) as total, SUM({IS_ACTIVE_SQL}) as active FROM cases WHERE district = ? GROUP BY court",
        (district_name,),
    ).fetchall()

    court_breakdown = []
    for row in court_rows:
        j_row = conn.execute(
            "SELECT judge FROM cases WHERE court = ? LIMIT 1", (row["court"],)
        ).fetchone()
        clr_rate = (
            int(((row["total"] - row["active"]) / row["total"]) * 100)
            if row["total"] > 0
            else 0
        )
        court_breakdown.append(
            {
                "name": row["court"] or "Unknown",
                "total": row["total"],
                "active": row["active"],
                "presiding_judge": j_row["judge"] if j_row else "N/A",
                "clearance": clr_rate,
                "status": "Optimal" if clr_rate > 80 else "Lagging",
            }
        )

    # Judges count
    total_judges = conn.execute(
        "SELECT COUNT(DISTINCT judge) FROM cases WHERE district = ?",
        (district_name,),
    ).fetchone()[0]

    # Courts count
    total_courts = conn.execute(
        "SELECT COUNT(DISTINCT court) FROM cases WHERE district = ?",
        (district_name,),
    ).fetchone()[0]

    # Judge Data
    judge_rows = conn.execute(
        f"SELECT judge, COUNT(*) as total, SUM({IS_ACTIVE_SQL}) as active FROM cases WHERE district = ? GROUP BY judge",
        (district_name,),
    ).fetchall()

    judge_breakdown = []
    for row in judge_rows:
        j_total = row["total"]
        j_active = row["active"]
        clr_rate = int(((j_total - j_active) / j_total) * 100) if j_total > 0 else 0
        judge_breakdown.append(
            {
                "name": row["judge"] or "Unknown",
                "total": j_total,
                "active": j_active,
                "clearance": clr_rate,
                "status": "Optimal" if clr_rate > 80 else "Lagging",
            }
        )

    # Recent Cases
    recent_rows = conn.execute(
        "SELECT * FROM cases WHERE district = ? ORDER BY filing_date DESC, id DESC LIMIT 5",
        (district_name,),
    ).fetchall()
    recent_cases = [Case(**dict(row)) for row in recent_rows]

    conn.close()

    return {
        "name": district_name,
        "total_cases": total,
        "active_cases": active,
        "success_rate": success_rate,
        "court_breakdown": court_breakdown,
        "judge_breakdown": judge_breakdown,
        "recent_cases": recent_cases,
        "total_judges": total_judges,
        "total_courts": total_courts,
    }


def get_court_stats(court: str) -> Dict[str, Any]:
    conn = get_db_connection()

    # Core Counts
    counts = conn.execute(
        f"SELECT COUNT(*) as total, SUM({IS_ACTIVE_SQL}) as active FROM cases WHERE court = ?",
        (court,),
    ).fetchone()

    total = counts["total"] or 0
    active = counts["active"] or 0

    # Clearance Rate
    closed = total - active
    clearance_rate = int((closed / total) * 100) if total > 0 else 0

    # Judge Data
    judge_rows = conn.execute(
        f"SELECT judge, COUNT(*) as total, SUM({IS_ACTIVE_SQL}) as active FROM cases WHERE court = ? GROUP BY judge",
        (court,),
    ).fetchall()

    formatted_judges = []
    for row in judge_rows:
        j_total = row["total"]
        j_active = row["active"]
        retention = int((j_active / j_total) * 100) if j_total > 0 else 0
        formatted_judges.append(
            {
                "name": row["judge"] or "Unknown",
                "active": j_active,
                "total": j_total,
                "retention": retention,
                "status": "Active" if retention > 20 else "Efficient",
            }
        )

    conn.close()

    return {
        "active_cases": active,
        "judges": formatted_judges,
        "name": court,
        "total_cases": total,
        "clearance_rate": clearance_rate,
        "overturned_rate": 0,
    }


def get_judge_stats(judge_name: str) -> Dict[str, Any]:
    conn = get_db_connection()

    # Core Counts
    counts = conn.execute(
        f"SELECT COUNT(*) as total, SUM({IS_ACTIVE_SQL}) as active FROM cases WHERE judge = ?",
        (judge_name,),
    ).fetchone()

    total = counts["total"] or 0
    active = counts["active"] or 0

    # District & Court (Most frequent)
    location = conn.execute(
        "SELECT district, court FROM cases WHERE judge = ? GROUP BY district, court ORDER BY COUNT(*) DESC LIMIT 1",
        (judge_name,),
    ).fetchone()

    district = location["district"] if location else "N/A"
    court = location["court"] if location else "N/A"

    # Verdict Distribution
    verdict_rows = conn.execute(
        f"SELECT {VERDICT_SQL} as v, COUNT(*) as c FROM cases WHERE judge = ? GROUP BY v",
        (judge_name,),
    ).fetchall()
    v_stats = {row["v"]: row["c"] for row in verdict_rows}

    # Recent cases
    recent_rows = conn.execute(
        "SELECT * FROM cases WHERE judge = ? ORDER BY filing_date DESC, id DESC LIMIT 10",
        (judge_name,),
    ).fetchall()
    recent_cases = [Case(**dict(row)) for row in recent_rows]

    conn.close()

    return {
        "name": judge_name,
        "total_cases": total,
        "active_cases": active,
        "closed_cases": total - active,
        "district": district,
        "court": court,
        "district_breakdown": {district: total},  # Simple fallback
        "verdict_breakdown": v_stats,
        "recent_cases": recent_cases,
    }
