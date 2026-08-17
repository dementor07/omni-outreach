"""Lead-source preview surface.

  POST /sources/naukri/preview   scrape Naukri for one keyword and return the
                                 deduped company list synchronously

The ``source.naukri`` *node* is async (intent -> bus -> Rust muscle -> companies
land on a lead). That's correct inside a running workflow but gives an operator
no way to *see what a keyword returns* before building one. This route is that
preview: a synchronous Camoufox scrape, no bus, no lead, no persistence. The
result shape matches what a real run produces (same dedup + clean_company_name),
so the Lead Sources panel doubles as a sanity check on a keyword/location combo.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.services import naukri_preview

log = logging.getLogger(__name__)

router = APIRouter()


class NaukriPreviewRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=120, description="One role keyword, e.g. 'SDR'")
    location: str | None = Field(None, max_length=120, description="Optional Naukri location filter")
    max_pages: int = Field(1, ge=1, le=5, description="Pages to scrape (~20 jobs/page). Capped at 5 for a preview.")


class NaukriPreviewCompany(BaseModel):
    company_name: str
    title: str
    role_count: int
    location: str
    experience: str
    source_url: str


class NaukriPreviewResponse(BaseModel):
    keyword: str
    jobs_returned: int
    companies_extracted: int
    companies: list[NaukriPreviewCompany]


@router.post(
    "/naukri/preview",
    response_model=NaukriPreviewResponse,
    summary="Preview a Naukri scrape (synchronous)",
    description=(
        "Scrapes Naukri.com for one role keyword via the Camoufox service and "
        "returns the deduped hiring-company list immediately. No workflow, no "
        "lead, no persistence — a dry run to validate a keyword before wiring a "
        "source.naukri node. Capped at 5 pages."
    ),
)
async def preview_naukri(
    body: NaukriPreviewRequest,
    _: AuthContext = Depends(get_current_workspace),
) -> NaukriPreviewResponse:
    try:
        result = await naukri_preview.preview_naukri(
            body.keyword, location=body.location, max_pages=body.max_pages
        )
    except naukri_preview.PreviewError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    return NaukriPreviewResponse(
        keyword=result.keyword,
        jobs_returned=result.jobs_returned,
        companies_extracted=len(result.companies),
        companies=[NaukriPreviewCompany(**vars(c)) for c in result.companies],
    )
