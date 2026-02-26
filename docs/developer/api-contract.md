# API Contracts

`Scholarr` is designed with strictly typed Pydantic V2 models, serialized across the network through standard OpenAPI `v3` specs via FastAPI.

## DTO Models Structure
FastAPI routes dynamically ingest request/response Data Transfer Objects.
- **Example**: `PublicationListItem` no longer contains a hard-coded `.doi`. It contains a `.display_identifier` property resolving the highest confidence identifier regardless of backend origin.
- **Testing**: Run `./scripts/check_frontend_api_contract.py` or equivalent integration steps mapped in CI to ensure that backend python routes strictly map to the TypeScript types compiled by the Frontend.

## Frontend Contract Requirements
The UI exclusively calls routes exposed by FastAPI's `APIRouter`. 
All frontend integration tests enforce that Vue 3 Components do not assume hard properties directly outside the bounded TS schemas. This avoids type mismatch runtime explosions if the database is scaled horizontally.
