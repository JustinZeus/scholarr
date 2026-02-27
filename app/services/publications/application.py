from __future__ import annotations

from app.services.publications.counts import (
    count_favorite_for_user,
    count_for_user,
    count_latest_for_user,
    count_unread_for_user,
)
from app.services.publications.enrichment import (
    hydrate_pdf_enrichment_state,
    schedule_missing_pdf_enrichment_for_user,
    schedule_retry_pdf_enrichment_for_row,
)
from app.services.publications.listing import (
    list_for_user,
    list_unread_for_user,
    retry_pdf_for_user,
)
from app.services.publications.modes import (
    MODE_ALL,
    MODE_LATEST,
    MODE_NEW,
    MODE_UNREAD,
    resolve_publication_view_mode,
)
from app.services.publications.pdf_queue import (
    count_pdf_queue_items,
    enqueue_all_missing_pdf_jobs,
    enqueue_retry_pdf_job_for_publication_id,
    list_pdf_queue_items,
    list_pdf_queue_page,
)
from app.services.publications.queries import (
    get_latest_run_id_for_user,
    get_publication_item_for_user,
    publications_query,
)
from app.services.publications.read_state import (
    mark_all_unread_as_read_for_user,
    mark_selected_as_read_for_user,
    set_publication_favorite_for_user,
)
from app.services.publications.types import PublicationListItem, UnreadPublicationItem

__all__ = [
    "MODE_ALL",
    "MODE_LATEST",
    "MODE_NEW",
    "MODE_UNREAD",
    "PublicationListItem",
    "UnreadPublicationItem",
    "count_favorite_for_user",
    "count_for_user",
    "count_latest_for_user",
    "count_pdf_queue_items",
    "count_unread_for_user",
    "enqueue_all_missing_pdf_jobs",
    "enqueue_retry_pdf_job_for_publication_id",
    "get_latest_run_id_for_user",
    "get_publication_item_for_user",
    "hydrate_pdf_enrichment_state",
    "list_for_user",
    "list_pdf_queue_items",
    "list_pdf_queue_page",
    "list_unread_for_user",
    "mark_all_unread_as_read_for_user",
    "mark_selected_as_read_for_user",
    "publications_query",
    "resolve_publication_view_mode",
    "retry_pdf_for_user",
    "schedule_missing_pdf_enrichment_for_user",
    "schedule_retry_pdf_enrichment_for_row",
    "set_publication_favorite_for_user",
]
