# Domain Boundaries

## Data Model Rules

- Scholar tracking is user-scoped.
- Publications are global/deduplicated records.
- Read/favorite/visibility state stays on scholar-publication link rows.

## Service Boundaries

Canonical business logic belongs in `app/services/domains/*`.

- `app/services/domains/ingestion/*`: run orchestration, continuation queue, scheduler, and scrape safety.
- `app/services/domains/scholar/*`: fail-fast scholar parsing and source fetch adapters.
- `app/services/domains/scholars/*`: scholar CRUD, profile image, and name-search controls.
- `app/services/domains/publications/*`: listing/read-state, favorite toggles, enrichment scheduling, and retry paths.
- `app/services/domains/crossref/*` + `app/services/domains/unpaywall/*`: DOI/OA enrichment with bounded pacing.
- `app/services/domains/runs/*`: run history and continuation queue operations.
- `app/services/domains/portability/*`: import/export workflows.

## Frontend Behavior Notes

- Navigation: Mobile primary nav is in a left drawer and closes on route change or logout.
- Lists: Long list views use internal scroll containers to prevent viewport overflow.
- Rate Limiting: Name search remains intentionally constrained due to upstream anti-bot behavior; production onboarding should prefer scholar ID/profile URLs directly if possible.

## Data Integration & Acquisition Flow

```mermaid
graph TD
    UI[Frontend Vue App] --> API[FastAPI Backend]
    API --> Scheduler[Background Celery/Async Scheduler]
    
    Scheduler -->|1. Fetch HTML| Scholar[Google Scholar HTML Parser]
    Scholar -->|2. Extract Metadata| IdentifierModule[Identifier Gathering]
    
    IdentifierModule -->|Search arXiv API| API1(arXiv)
    IdentifierModule -->|Search Crossref API| API2(Crossref)
    
    IdentifierModule -->|3. Save Identifiers| DB[(PostgreSQL)]
    
    Scheduler -->|4. Resolve PDF| PDFPipeline[PDF Resolution Pipeline]
    DB --> |Identified DOIs| PDFPipeline
    PDFPipeline -->|Search Open Access APIs| Unpaywall(Unpaywall API)
    
    Unpaywall --> |Acquire PDF URL| PDFWorker[PDF Download Worker]
    PDFWorker --> |Store PDF Metadata| DB 
```

### Identifier Engine Philosophy
The platform previously treated the `DOI` as a hardcoded 1:1 property of a publication. It now utilizes a decoupled *Identifier Gathering* module (`PublicationIdentifier` table). A single publication can have multiple identifiers (ex. `doi`, `arxiv`, `pmid`, `pmcid`). This creates high resilience when integrating with external APIs, allowing systems like Unpaywall to be fed explicitly with high-confidence DOIs, rather than relying on unstructured search heuristics.
