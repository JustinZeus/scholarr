
import asyncio
from sqlalchemy import select, func
from app.db.session import get_session_factory
from app.db.models import Publication, ScholarPublication

async def check_publications():
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Total publications
        total_pubs = await session.execute(select(func.count()).select_from(Publication))
        print(f"Total Publications: {total_pubs.scalar()}")

        # Total scholar links
        total_links = await session.execute(select(func.count()).select_from(ScholarPublication))
        print(f"Total Scholar-Publication Links: {total_links.scalar()}")

        # Check for orphans
        orphans = await session.execute(
            select(func.count())
            .select_from(Publication)
            .outerjoin(ScholarPublication, Publication.id == ScholarPublication.publication_id)
            .where(ScholarPublication.publication_id == None)
        )
        print(f"Orphaned Publications (no link): {orphans.scalar()}")

        # Check sorting behavior
        latest_links = await session.execute(
            select(Publication.title_raw, ScholarPublication.created_at)
            .join(ScholarPublication, Publication.id == ScholarPublication.publication_id)
            .order_by(ScholarPublication.created_at.desc())
            .limit(10)
        )
        print("\nLatest 10 links by created_at:")
        for row in latest_links:
            print(f"- {row.created_at}: {row.title_raw[:50]}")

if __name__ == "__main__":
    asyncio.run(check_publications())
