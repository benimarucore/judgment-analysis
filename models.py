from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime


class Case(BaseModel):
    accused: Optional[str] = ""
    complaininat: Optional[str] = Field(None, alias="complaintant")
    prosecution: Optional[str] = ""
    court: Optional[str] = ""
    sentence_issued: Optional[str] = ""
    corno: str
    chargesheet: Optional[str] = ""
    plea: Optional[str] = ""
    defense: Optional[str] = ""
    judge: Optional[str] = ""
    district: Optional[str] = ""
    date: Optional[str] = ""
    filing_date: Optional[datetime] = None
    summary: Optional[str] = None

    @validator("complaininat", pre=True, always=True)
    def check_aliases(cls, v, values):
        return v

    @validator("complaininat", pre=True)
    def handle_typo(cls, v, values):
        return v

    class Config:
        populate_by_name = True

    @property
    def is_active(self) -> bool:
        # A case is active ONLY if:
        # 1. No sentence/verdict is issued
        # 2. AND No judgment date is recorded
        # If a date is present, it's a closed/judged case, even if we don't know the exact verdict.

        lower_date = (self.date or "").lower().strip()
        invalid_dates = [
            "not specified",
            "not mentioned",
            "unknown",
            "none",
            "not provided",
        ]
        has_date = bool(lower_date and not any(d in lower_date for d in invalid_dates))

        # Check explicit sentence/verdict field
        lower_sentence = (self.sentence_issued or "").lower()
        invalid_markers = ["not specified", "not mentioned", "unknown", "none"]
        has_valid_sentence = lower_sentence and not any(
            m in lower_sentence for m in invalid_markers
        )

        if has_date:
            return False

        if has_valid_sentence:
            return False

        return True

    @property
    def verdict(self) -> str:
        if self.is_active:
            return "Pending"

        # Check explicit sentence/verdict field first
        lower_sentence = (self.sentence_issued or "").lower()

        # known "Not specified" variations
        invalid_markers = ["not specified", "not mentioned", "unknown", "none"]
        is_valid_sentence = lower_sentence and not any(
            m in lower_sentence for m in invalid_markers
        )

        if is_valid_sentence:
            if "acquitte" in lower_sentence or "not guilty" in lower_sentence:
                return "Acquittal"
            if "convict" in lower_sentence or "guilty" in lower_sentence:
                return "Conviction"
            if "dismiss" in lower_sentence:
                return "Dismissed"

        # Fallback to Summary
        if self.summary:
            lower_summary = self.summary.lower()
            if (
                "acquittal" in lower_summary
                or "acquitted" in lower_summary
                or "not guilty" in lower_summary
            ):
                return "Acquittal"
            if (
                "conviction" in lower_summary
                or "convicted" in lower_summary
                or "guilty" in lower_summary
            ):
                return "Conviction"
            if "dismiss" in lower_summary:
                return "Dismissed"

        # If it's closed (has date) but we couldn't determine Conviction/Acquittal
        return "Decided"

    @property
    def formatted_date(self) -> str:
        if self.filing_date:
            return self.filing_date.strftime("%d %b %Y")  # 09 Oct 2025
        return self.date or "N/A"
