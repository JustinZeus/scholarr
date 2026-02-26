import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.settings import settings
from app.db.models import ScholarProfile
from app.services.domains.ingestion.application import ScholarIngestionService
from app.services.domains.scholar.parser_types import PublicationCandidate
from app.services.domains.openalex.client import OpenAlexClient

async def main():
    service = ScholarIngestionService()
    scholar = ScholarProfile(
        id=1,
        scholar_id="SaiiI5MAAAAJ",
        name="Test Scholar"
    )
    pubs = [
        PublicationCandidate(
            title="A fast quantum mechanical algorithm for database search",
            year=1996,
            citation_count=1000,
            authors_text="LK Grover",
            venue_text="Proceedings of the 28th Annual ACM Symposium on the Theory of Computing",
            cluster_id=None,
            title_url=None,
            pdf_url=None
        )
    ]
    
    print("Enriching...")
    try:
        enriched = await service._enrich_publications_with_openalex(scholar, pubs)
        for p in enriched:
            print(f"Title: {p.title}")
            print(f"Year: {p.year}")
            print(f"Citations: {p.citation_count}")
            print(f"PDF URL: {p.pdf_url}")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
