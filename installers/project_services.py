import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification

from .models import (
    ProviderSubscriptionPlan,
    ServicePortfolio,
    ServiceProjectEvent,
    ServiceProjectModerationLog,
)


logger = logging.getLogger(__name__)


DEFAULT_PROJECT_LIMITS = {
    "free": {
        "max_projects": 1,
        "max_project_media": 5,
        "max_project_videos": 1,
        "max_local_video_uploads": 0,
        "max_video_size_mb": 0,
        "project_analytics_enabled": False,
        "project_leads_enabled": True,
        "featured_project_slots": 0,
        "project_product_links_limit": 2,
    },
    "basic": {
        "max_projects": 5,
        "max_project_media": 8,
        "max_project_videos": 2,
        "max_local_video_uploads": 1,
        "max_video_size_mb": 50,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 0,
        "project_product_links_limit": 5,
    },
    "plus": {
        "max_projects": 20,
        "max_project_media": 15,
        "max_project_videos": 5,
        "max_local_video_uploads": 5,
        "max_video_size_mb": 150,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 2,
        "project_product_links_limit": 15,
    },
    "pro": {
        "max_projects": 100,
        "max_project_media": 30,
        "max_project_videos": 15,
        "max_local_video_uploads": 20,
        "max_video_size_mb": 300,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 8,
        "project_product_links_limit": 30,
    },
    "enterprise": {
        "max_projects": -1,
        "max_project_media": 60,
        "max_project_videos": -1,
        "max_local_video_uploads": -1,
        "max_video_size_mb": 500,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": -1,
        "project_product_links_limit": -1,
    },
}


def _normalized_plan_name(provider):
    value = (getattr(provider, "subscription_plan", "") or "free").strip().lower()
    if "enterprise" in value:
        return "enterprise"
    if "pro" in value or "special" in value:
        return "pro"
    if "plus" in value or "standard" in value:
        return "plus"
    if "basic" in value:
        return "basic"
    return "free"


def _plan_overrides(provider):
    plan_name = getattr(provider, "subscription_plan", "") or ""
    plan = ProviderSubscriptionPlan.objects.filter(name__iexact=plan_name, is_active=True).first()
    benefits = plan.benefits if plan and isinstance(plan.benefits, dict) else {}
    return benefits.get("projects", benefits) if isinstance(benefits, dict) else {}


@dataclass
class ProjectEntitlement:
    allowed: bool
    limit: int
    used: int
    remaining: int
    upgrade_required: bool
    message: str

    def as_dict(self):
        return {
            "allowed": self.allowed,
            "limit": self.limit if self.limit >= 0 else "unlimited",
            "used": self.used,
            "remaining": self.remaining if self.remaining >= 0 else "unlimited",
            "upgrade_required": self.upgrade_required,
            "message": self.message,
        }


class ProjectEntitlementService:
    def __init__(self, provider):
        self.provider = provider
        tier = _normalized_plan_name(provider)
        configured = getattr(settings, "PROJECT_SUBSCRIPTION_LIMITS", {}) or {}
        self.limits = {
            **DEFAULT_PROJECT_LIMITS.get(tier, DEFAULT_PROJECT_LIMITS["free"]),
            **configured.get(tier, {}),
            **_plan_overrides(provider),
        }
        if getattr(provider, "subscription_status", "inactive") not in {"active", "trial"}:
            self.limits = {
                **DEFAULT_PROJECT_LIMITS["free"],
                **configured.get("free", {}),
            }

    def _usage(self):
        return self.provider.portfolio_items.exclude(
            approval_status=ServicePortfolio.STATUS_REJECTED
        ).count()

    def can_create_project(self):
        limit = int(self.limits.get("max_projects", 0))
        used = self._usage()
        allowed = limit < 0 or used < limit
        return ProjectEntitlement(
            allowed=allowed,
            limit=limit,
            used=used,
            remaining=-1 if limit < 0 else max(limit - used, 0),
            upgrade_required=not allowed,
            message="" if allowed else "You have reached your current project limit. Upgrade your plan or manage existing projects.",
        )

    def can_publish_project(self):
        result = self.can_create_project()
        if not self.provider.approval_allows_dashboard:
            return ProjectEntitlement(
                False, result.limit, result.used, result.remaining, False,
                "Your provider account must be approved before projects can be published.",
            )
        return result

    def can_add_project_media(self, project):
        limit = int(self.limits.get("max_project_media", 0))
        used = project.media_items.count()
        allowed = limit < 0 or used < limit
        return ProjectEntitlement(
            allowed, limit, used, -1 if limit < 0 else max(limit - used, 0),
            not allowed,
            "" if allowed else "This project has reached the media limit for your current plan.",
        )

    def can_upload_local_video(self, project=None):
        limit = int(self.limits.get("max_local_video_uploads", 0))
        used = self.provider.portfolio_items.exclude(local_video="").exclude(local_video__isnull=True).count()
        allowed = bool(getattr(settings, "LOCAL_PROJECT_VIDEO_UPLOADS_ENABLED", False)) and (limit < 0 or used < limit)
        message = ""
        if not getattr(settings, "LOCAL_PROJECT_VIDEO_UPLOADS_ENABLED", False):
            message = "Direct video uploads are not enabled yet. Add a YouTube or supported external video URL."
        elif not allowed:
            message = "Direct video upload is not included in your current project allowance."
        return ProjectEntitlement(
            allowed, limit, used, -1 if limit < 0 else max(limit - used, 0),
            not allowed and limit == 0, message,
        )

    def payload(self):
        creation = self.can_create_project()
        return {
            **creation.as_dict(),
            "can_create_project": creation.allowed,
            "can_publish_project": self.can_publish_project().allowed,
            "can_upload_local_video": self.can_upload_local_video().allowed,
            "project_limit": creation.as_dict()["limit"],
            "projects_used": creation.used,
            "remaining_projects": creation.as_dict()["remaining"],
            "max_media_per_project": self.limits.get("max_project_media", 0),
            "max_project_videos": self.limits.get("max_project_videos", 0),
            "max_video_size_mb": self.limits.get("max_video_size_mb", 0),
            "analytics_enabled": bool(self.limits.get("project_analytics_enabled")),
            "project_leads_enabled": bool(self.limits.get("project_leads_enabled")),
            "featured_project_slots": self.limits.get("featured_project_slots", 0),
            "max_product_links": self.limits.get("project_product_links_limit", 0),
        }


def record_project_event(project, event_type, request=None, source="", metadata=None):
    user = getattr(request, "user", None) if request else None
    if not getattr(user, "is_authenticated", False):
        user = None
    session_key = ""
    if request and getattr(request, "session", None):
        session_key = request.session.session_key or ""
    event = ServiceProjectEvent.objects.create(
        project=project,
        user=user,
        event_type=event_type,
        session_key=session_key,
        source=source,
        metadata=metadata or {},
    )
    counter = {
        "view": "views_count",
        "video_view": "video_views_count",
        "product_click": "product_click_count",
        "provider_click": "provider_click_count",
        "share": "shares_count",
        "save": "saves_count",
        "quote_request": "quote_requests_count",
    }.get(event_type)
    if counter:
        ServicePortfolio.objects.filter(pk=project.pk).update(**{counter: F(counter) + 1})
    return event


def safe_project_email(subject, message, recipients):
    recipients = [email for email in recipients if email]
    if not recipients:
        return False
    try:
        send_mail(
            subject,
            message,
            getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipients,
            fail_silently=True,
        )
        return True
    except Exception:
        logger.exception("Project email failed: %s", subject)
        return False


def notify_project_submitted(project):
    admin_path = reverse("admin:installers_serviceportfolio_change", args=[project.pk])
    staff_users = project.provider.user.__class__.objects.filter(is_staff=True, is_active=True)
    for staff in staff_users:
        Notification.send(
            staff,
            "system",
            "Project awaiting review",
            f"{project.provider.business_name} submitted “{project.title}”.",
            link=admin_path,
            metadata={"service_project_id": project.id, "target_screen": "StaffProjectDetail"},
            priority=3,
        )
    safe_project_email(
        "Arolana project awaiting review",
        f"{project.provider.business_name} submitted {project.title}.\n\n{admin_path}",
        staff_users.exclude(email="").values_list("email", flat=True),
    )


@transaction.atomic
def moderate_project(project, new_status, actor=None, notes=""):
    old_status = project.approval_status
    project.approval_status = new_status
    project.moderation_notes = notes
    if new_status == ServicePortfolio.STATUS_APPROVED:
        project.published_at = project.published_at or timezone.now()
        project.is_active = True
    elif new_status in {ServicePortfolio.STATUS_REJECTED, ServicePortfolio.STATUS_SUSPENDED}:
        project.is_active = False
    project.save()
    ServiceProjectModerationLog.objects.create(
        project=project,
        actor=actor,
        old_status=old_status,
        new_status=new_status,
        notes=notes,
    )
    title_map = {
        ServicePortfolio.STATUS_APPROVED: "Project approved",
        ServicePortfolio.STATUS_REQUIRES_CHANGES: "Project changes requested",
        ServicePortfolio.STATUS_REJECTED: "Project rejected",
        ServicePortfolio.STATUS_SUSPENDED: "Project suspended",
    }
    title = title_map.get(new_status, "Project status updated")
    Notification.send(
        project.provider.user,
        "system",
        title,
        notes or f"Your project “{project.title}” is now {project.get_approval_status_display().lower()}.",
        link=reverse("installers:provider_project_edit", args=[project.pk]),
        metadata={"service_project_id": project.id, "target_screen": "ProviderProjectDetail"},
        priority=3,
    )
    safe_project_email(
        f"Arolana: {title}",
        notes or f"Your project “{project.title}” is now {project.get_approval_status_display().lower()}.",
        [project.provider.email, project.provider.user.email],
    )
    return project
