from catalog_imports.models import ImportAuditEvent, ImportItem


def record_event(item: ImportItem, event_type: str, message: str = "", payload=None):
    return ImportAuditEvent.objects.create(
        item=item,
        event_type=event_type,
        message=(message or "")[:500],
        payload=payload or {},
    )
