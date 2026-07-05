from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from products.models import Product

from .api_views import provider_from_request, provider_user_from_request, request_user_from_mobile_payload
from .models import (
    SavedServiceProject,
    ServiceCategory,
    ServicePortfolio,
    ServiceProjectMedia,
    ServiceProjectProduct,
    ServiceProjectReport,
    ServiceQuoteRequest,
)
from .project_services import (
    ProjectEntitlementService,
    moderate_project,
    notify_project_submitted,
    record_project_event,
)
from .serializers import (
    ServiceCategorySerializer,
    ServicePortfolioSerializer,
    ServiceProjectMediaSerializer,
    ServiceProjectMediaWriteSerializer,
    ServiceProjectWriteSerializer,
)
from .services import notify_staff_service_quote


class ProjectPagination(PageNumberPagination):
    page_size = 18
    page_size_query_param = "page_size"
    max_page_size = 48


def _public_projects():
    return ServicePortfolio.objects.public().optimized()


def _project_lookup(queryset, value):
    lookup = Q(slug=value)
    if str(value).isdigit():
        lookup |= Q(pk=int(value))
    return get_object_or_404(queryset, lookup)


class PublicProjectListAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        queryset = _public_projects()
        query = (request.query_params.get("q") or "").strip()
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(short_summary__icontains=query)
                | Q(description__icontains=query)
                | Q(provider__business_name__icontains=query)
                | Q(service_category__name__icontains=query)
                | Q(city__icontains=query)
                | Q(state__icontains=query)
                | Q(project_products__product__name__icontains=query)
            ).distinct()
        filters = {
            "service_category__slug": request.query_params.get("category"),
            "country__iexact": request.query_params.get("country"),
            "state__iexact": request.query_params.get("state"),
            "city__iexact": request.query_params.get("city"),
            "project_type": request.query_params.get("project_type"),
            "provider__provider_type": request.query_params.get("provider_type"),
            "project_products__product_id": request.query_params.get("product"),
        }
        for key, value in filters.items():
            if value:
                queryset = queryset.filter(**{key: value})
        if request.query_params.get("verified") in {"1", "true", "yes"}:
            queryset = queryset.filter(is_verified_project=True)
        ordering = request.query_params.get("ordering")
        ordering_map = {
            "latest": "-published_at",
            "popular": "-views_count",
            "most_requested": "-quote_requests_count",
            "most_watched": "-video_views_count",
        }
        queryset = queryset.order_by(ordering_map.get(ordering, "-is_featured"), "-published_at")
        paginator = ProjectPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ServicePortfolioSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


class PublicProjectDetailAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, project_ref):
        project = _project_lookup(_public_projects(), project_ref)
        record_project_event(project, "view", request=request, source=request.query_params.get("source", "api"))
        project.refresh_from_db()
        related = _public_projects().filter(service_category=project.service_category).exclude(pk=project.pk)[:6]
        return Response({
            "project": ServicePortfolioSerializer(project, context={"request": request}).data,
            "related_projects": ServicePortfolioSerializer(related, many=True, context={"request": request}).data,
        })


class FeaturedProjectsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        projects = _public_projects().filter(is_featured=True)[:12]
        return Response({"projects": ServicePortfolioSerializer(projects, many=True, context={"request": request}).data})


class ProjectCategoriesAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        categories = ServiceCategory.objects.filter(is_active=True).annotate(
            project_count=Count(
                "projects",
                filter=Q(
                    projects__approval_status=ServicePortfolio.STATUS_APPROVED,
                    projects__is_active=True,
                ),
                distinct=True,
            )
        ).order_by("name")
        return Response({
            "categories": ServiceCategorySerializer(categories, many=True, context={"request": request}).data,
        })


class ProviderPublicProjectsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, provider_id):
        projects = _public_projects().filter(provider_id=provider_id)
        return Response({"projects": ServicePortfolioSerializer(projects, many=True, context={"request": request}).data})


class ProjectEventAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    event_type = "view"

    def post(self, request, project_ref):
        project = _project_lookup(_public_projects(), project_ref)
        record_project_event(
            project,
            self.event_type,
            request=request,
            source=str(request.data.get("source", "mobile"))[:80],
            metadata=request.data.get("metadata") if isinstance(request.data.get("metadata"), dict) else {},
        )
        return Response({"success": True})


class ProjectSaveAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, project_ref):
        user = request.user if request.user.is_authenticated else request_user_from_mobile_payload(request)
        if not user:
            return Response({"detail": "Sign in to save projects.", "login_required": True}, status=status.HTTP_401_UNAUTHORIZED)
        project = _project_lookup(_public_projects(), project_ref)
        saved, created = SavedServiceProject.objects.get_or_create(project=project, user=user)
        if not created and request.data.get("remove"):
            saved.delete()
            ServicePortfolio.objects.filter(pk=project.pk, saves_count__gt=0).update(saves_count=project.saves_count - 1)
            return Response({"saved": False})
        if created:
            record_project_event(project, "save", request=request, source="mobile")
        return Response({"saved": True})


class ProjectReportAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, project_ref):
        project = _project_lookup(_public_projects(), project_ref)
        user = request.user if request.user.is_authenticated else request_user_from_mobile_payload(request)
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            return Response({"detail": "Choose a report reason."}, status=status.HTTP_400_BAD_REQUEST)
        report = ServiceProjectReport.objects.create(
            project=project,
            reporter=user,
            reason=reason[:120],
            details=str(request.data.get("details", "")).strip(),
        )
        return Response({"success": True, "report_id": report.id}, status=status.HTTP_201_CREATED)


class ProjectSimilarQuoteAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, project_ref):
        project = _project_lookup(_public_projects(), project_ref)
        user = request.user if request.user.is_authenticated else request_user_from_mobile_payload(request)
        data = request.data
        quote = ServiceQuoteRequest.objects.create(
            customer=user,
            provider=project.provider,
            category=project.service_category,
            source_project=project,
            product_id=project.project_products.filter(is_primary_product=True).values_list("product_id", flat=True).first(),
            name=str(data.get("name") or (user.get_full_name() if user else "")).strip() or "Arolana customer",
            phone=str(data.get("phone", "")).strip(),
            whatsapp=str(data.get("whatsapp", "")).strip(),
            email=str(data.get("email") or (getattr(user, "email", "") if user else "")).strip(),
            state=str(data.get("state") or project.state).strip(),
            city=str(data.get("city") or project.city).strip(),
            address=str(data.get("address", "")).strip(),
            service_needed=str(data.get("service_needed") or f"Similar project: {project.title}")[:220],
            message=str(data.get("message") or f"I would like a quote for a project similar to “{project.title}”.").strip(),
            budget=data.get("budget") or None,
            contact_preference=str(data.get("contact_preference", "")).strip(),
            urgency=str(data.get("urgency", "normal")).strip(),
        )
        notify_staff_service_quote(quote)
        record_project_event(project, "quote_request", request=request, source="project")
        return Response({
            "success": True,
            "message": "Your similar-project quote request has been sent.",
            "quote_id": quote.id,
        }, status=status.HTTP_201_CREATED)


class ProviderProjectsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        projects = provider.portfolio_items.optimized()
        return Response({
            "projects": ServicePortfolioSerializer(projects, many=True, context={"request": request}).data,
            "entitlements": ProjectEntitlementService(provider).payload(),
        })

    def post(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        entitlements = ProjectEntitlementService(provider)
        permission = entitlements.can_create_project()
        if not permission.allowed:
            return Response(permission.as_dict(), status=status.HTTP_403_FORBIDDEN)
        serializer = ServiceProjectWriteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            project = serializer.save(provider=provider, created_by=provider.user)
        except DjangoValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "message": "Project draft saved.",
            "project": ServicePortfolioSerializer(project, context={"request": request}).data,
            "entitlements": entitlements.payload(),
        }, status=status.HTTP_201_CREATED)


class ProviderProjectDetailAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def _project(self, request, project_id):
        provider, error = provider_from_request(request)
        if error:
            return None, None, error
        project = get_object_or_404(provider.portfolio_items.optimized(), pk=project_id)
        return provider, project, None

    def get(self, request, project_id):
        provider, project, error = self._project(request, project_id)
        if error:
            return error
        return Response({
            "project": ServicePortfolioSerializer(project, context={"request": request}).data,
            "entitlements": ProjectEntitlementService(provider).payload(),
        })

    def patch(self, request, project_id):
        provider, project, error = self._project(request, project_id)
        if error:
            return error
        if project.approval_status == ServicePortfolio.STATUS_SUSPENDED:
            return Response({"detail": "Suspended projects cannot be edited."}, status=status.HTTP_403_FORBIDDEN)
        serializer = ServiceProjectWriteSerializer(project, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        project = serializer.save()
        if project.approval_status == ServicePortfolio.STATUS_APPROVED:
            project.approval_status = ServicePortfolio.STATUS_PENDING
            project.save(update_fields=["approval_status", "updated_at"])
        return Response({
            "message": "Project changes saved.",
            "project": ServicePortfolioSerializer(project, context={"request": request}).data,
        })

    def delete(self, request, project_id):
        _provider, project, error = self._project(request, project_id)
        if error:
            return error
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProviderProjectSubmitAPIView(ProviderProjectDetailAPIView):
    def post(self, request, project_id):
        provider, project, error = self._project(request, project_id)
        if error:
            return error
        permission = ProjectEntitlementService(provider).can_publish_project()
        if not permission.allowed:
            return Response(permission.as_dict(), status=status.HTTP_403_FORBIDDEN)
        if project.completion_percent < 60:
            return Response({
                "detail": "Complete the project story, category, location, outcome, and media before submission.",
                "completion_percent": project.completion_percent,
            }, status=status.HTTP_400_BAD_REQUEST)
        project.approval_status = ServicePortfolio.STATUS_PENDING
        project.moderation_notes = ""
        project.save(update_fields=["approval_status", "moderation_notes", "updated_at"])
        notify_project_submitted(project)
        return Response({
            "message": "Project submitted for Arolana review.",
            "project": ServicePortfolioSerializer(project, context={"request": request}).data,
        })


class ProviderProjectMediaAPIView(ProviderProjectDetailAPIView):
    def post(self, request, project_id):
        provider, project, error = self._project(request, project_id)
        if error:
            return error
        permission = ProjectEntitlementService(provider).can_add_project_media(project)
        if not permission.allowed:
            return Response(permission.as_dict(), status=status.HTTP_403_FORBIDDEN)
        if request.FILES.get("video") and not ProjectEntitlementService(provider).can_upload_local_video(project).allowed:
            return Response(ProjectEntitlementService(provider).can_upload_local_video(project).as_dict(), status=status.HTTP_403_FORBIDDEN)
        serializer = ServiceProjectMediaWriteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            media = serializer.save(project=project)
        except DjangoValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "message": "Project media uploaded for review.",
            "media": ServiceProjectMediaSerializer(media, context={"request": request}).data,
        }, status=status.HTTP_201_CREATED)


class ProviderProjectMediaDeleteAPIView(ProviderProjectDetailAPIView):
    def delete(self, request, project_id, media_id):
        _provider, project, error = self._project(request, project_id)
        if error:
            return error
        media = get_object_or_404(project.media_items, pk=media_id)
        media.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProviderProjectEntitlementsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        return Response(ProjectEntitlementService(provider).payload())


class ProviderProjectAnalyticsAPIView(ProviderProjectDetailAPIView):
    def get(self, request, project_id):
        provider, project, error = self._project(request, project_id)
        if error:
            return error
        if not ProjectEntitlementService(provider).payload()["analytics_enabled"]:
            return Response({"detail": "Project analytics require an eligible plan.", "upgrade_required": True}, status=status.HTTP_403_FORBIDDEN)
        return Response({
            "project_id": project.id,
            "views": project.views_count,
            "video_views": project.video_views_count,
            "product_clicks": project.product_click_count,
            "provider_clicks": project.provider_click_count,
            "saves": project.saves_count,
            "shares": project.shares_count,
            "quote_requests": project.quote_requests_count,
            "conversion_rate": round(project.quote_requests_count / max(project.views_count, 1) * 100, 2),
        })


class ProviderProjectLeadsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        provider, error = provider_from_request(request)
        if error:
            return error
        quotes = ServiceQuoteRequest.objects.filter(provider=provider, source_project__isnull=False).select_related("source_project")
        return Response({
            "leads": [
                {
                    "id": quote.id,
                    "project_id": quote.source_project_id,
                    "project_title": quote.source_project.title,
                    "name": quote.name,
                    "city": quote.city,
                    "state": quote.state,
                    "status": quote.status,
                    "created_at": quote.created_at,
                }
                for quote in quotes
            ]
        })


class StaffProjectsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        user = provider_user_from_request(request)
        if not user or not user.is_staff:
            return Response({"detail": "Arolana staff access is required."}, status=status.HTTP_403_FORBIDDEN)
        projects = ServicePortfolio.objects.optimized()
        status_filter = request.query_params.get("status")
        if status_filter:
            projects = projects.filter(approval_status=status_filter)
        query = request.query_params.get("q")
        if query:
            projects = projects.filter(Q(title__icontains=query) | Q(provider__business_name__icontains=query))
        return Response({"projects": ServicePortfolioSerializer(projects[:100], many=True, context={"request": request}).data})


class StaffProjectDetailAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def _staff_project(self, request, project_id):
        user = provider_user_from_request(request)
        if not user or not user.is_staff:
            return None, None, Response({"detail": "Arolana staff access is required."}, status=status.HTTP_403_FORBIDDEN)
        return user, get_object_or_404(ServicePortfolio.objects.optimized(), pk=project_id), None

    def get(self, request, project_id):
        _user, project, error = self._staff_project(request, project_id)
        if error:
            return error
        return Response({"project": ServicePortfolioSerializer(project, context={"request": request}).data})


class StaffProjectModerationAPIView(StaffProjectDetailAPIView):
    action_status = ""

    def post(self, request, project_id):
        user, project, error = self._staff_project(request, project_id)
        if error:
            return error
        project = moderate_project(
            project,
            self.action_status,
            actor=user,
            notes=str(request.data.get("notes", "")).strip(),
        )
        return Response({
            "message": f"Project marked {project.get_approval_status_display().lower()}.",
            "project": ServicePortfolioSerializer(project, context={"request": request}).data,
        })


class StaffProjectApproveAPIView(StaffProjectModerationAPIView):
    action_status = ServicePortfolio.STATUS_APPROVED


class StaffProjectRequireChangesAPIView(StaffProjectModerationAPIView):
    action_status = ServicePortfolio.STATUS_REQUIRES_CHANGES


class StaffProjectRejectAPIView(StaffProjectModerationAPIView):
    action_status = ServicePortfolio.STATUS_REJECTED


class StaffProjectFeatureAPIView(StaffProjectDetailAPIView):
    def post(self, request, project_id):
        _user, project, error = self._staff_project(request, project_id)
        if error:
            return error
        project.is_featured = bool(request.data.get("featured", True))
        project.save(update_fields=["is_featured", "updated_at"])
        return Response({"success": True, "is_featured": project.is_featured})


class StaffProjectVerifyAPIView(StaffProjectDetailAPIView):
    def post(self, request, project_id):
        _user, project, error = self._staff_project(request, project_id)
        if error:
            return error
        project.is_verified_project = bool(request.data.get("verified", True))
        project.save(update_fields=["is_verified_project", "updated_at"])
        return Response({"success": True, "is_verified_project": project.is_verified_project})
