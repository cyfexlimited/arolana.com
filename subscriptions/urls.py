from django.urls import path

from . import views


app_name = "subscriptions"

urlpatterns = [
    path("plans/", views.subscription_plans, name="plans"),
    path("subscribe/<int:plan_id>/", views.subscribe, name="subscribe"),
    path("cancel/<int:subscription_id>/", views.cancel_subscription, name="cancel"),
    path("undo-cancellation/", views.undo_cancellation_web, name="undo_cancellation"),
    path("schedule-downgrade/", views.schedule_downgrade_web, name="schedule_downgrade"),
    path("cancel-scheduled-change/", views.cancel_scheduled_change_web, name="cancel_scheduled_change"),
    path("auto-renew/", views.set_auto_renew_web, name="auto_renew"),
    path("renew/", views.renew_subscription_web, name="renew"),
    path("history/", views.subscription_history, name="history"),
    path("api/plans/", views.api_plans, name="api_plans"),
    path("api/plans/<int:plan_id>/", views.api_plan_detail, name="api_plan_detail"),
    path("api/current/", views.api_current, name="api_current"),
    path("api/checkout/", views.api_checkout, name="api_checkout"),
    path("api/payment-result/<str:reference>/", views.api_payment_result, name="api_payment_result"),
    path("api/verify-payment/", views.api_verify_payment, name="api_verify_payment"),
    path("api/renew/", views.api_renew, name="api_renew"),
    path("api/reconcile/", views.api_reconcile, name="api_reconcile"),
    path("api/cancel/", views.api_cancel, name="api_cancel"),
    path("api/undo-cancellation/", views.api_undo_cancellation, name="api_undo_cancellation"),
    path("api/downgrade/", views.api_downgrade, name="api_downgrade"),
    path("api/cancel-scheduled-change/", views.api_cancel_scheduled_change, name="api_cancel_scheduled_change"),
    path("api/auto-renew/", views.api_auto_renew, name="api_auto_renew"),
    path("api/history/", views.api_history, name="api_history"),
]
