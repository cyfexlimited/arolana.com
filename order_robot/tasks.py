from .services import run_robot_for_paid_orders


def run_paid_order_robot(limit=25):
    """Small synchronous task hook for cron, admin actions, or future Celery wiring."""
    return run_robot_for_paid_orders(limit=limit)
