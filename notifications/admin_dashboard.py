from django.contrib.admin import AdminSite
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from .models import Notification

class ArolanaAdminSite(AdminSite):
    site_header = 'Arolana Administration'
    site_title = 'Arolana Admin'
    index_title = 'Welcome to Arolana Admin Dashboard'
    
    def index(self, request, extra_context=None):
        # Get recent notifications for admin dashboard
        if request.user.is_superuser:
            recent_notifications = Notification.objects.filter(user=request.user)[:10]
            unread_notifications = recent_notifications.filter(is_read=False)
            
            extra_context = {
                'recent_notifications': recent_notifications,
                'unread_count': unread_notifications.count(),
                'notification_url': reverse('notifications:list')
            }
        return super().index(request, extra_context)

# Override the admin index template
cat > templates/admin/index.html << 'EOF'
{% extends "admin/index.html" %}
{% load i18n %}

{% block content %}
<div id="content-main">
    {% if app_list %}
        {% for app in app_list %}
            <div class="module">
                <h2>{{ app.name }}</h2>
                <table>
                    <caption>
                        <a href="{{ app.app_url }}" class="section">{% blocktranslate with name=app.name %}View {{ name }}{% endblocktranslate %}</a>
                    </caption>
                    {% for model in app.models %}
                        <tr class="model-{{ model.object_name|lower }}">
                            {% if model.admin_url %}
                                <th scope="row"><a href="{{ model.admin_url }}">{{ model.name }}</a></th>
                            {% else %}
                                <th scope="row">{{ model.name }}</th>
                            {% endif %}
                            
                            {% if model.add_url %}
                                <td><a href="{{ model.add_url }}" class="addlink">{% translate 'Add' %}</a></td>
                            {% else %}
                                <td></td>
                            {% endif %}
                            
                            {% if model.admin_url %}
                                {% if model.view_only %}
                                    <td><a href="{{ model.admin_url }}" class="viewlink">{% translate 'View' %}</a></td>
                                {% else %}
                                    <td><a href="{{ model.admin_url }}" class="changelink">{% translate 'Change' %}</a></td>
                                {% endif %}
                            {% else %}
                                <td></td>
                            {% endif %}
                        </tr>
                    {% endfor %}
                </table>
            </div>
        {% endfor %}
    {% else %}
        <p>{% translate 'You don’t have permission to view or edit anything.' %}</p>
    {% endif %}
    
    <!-- Quick Actions Widget -->
    <div class="module">
        <h2>Quick Actions</h2>
        <ul style="padding: 12px;">
            <li style="margin-bottom: 8px;">
                <a href="/admin/products/product/add/" class="button" style="display: inline-block; background: #3b82f6; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none;">
                    ➕ Add New Product
                </a>
            </li>
            <li style="margin-bottom: 8px;">
                <a href="/admin/orders/order/" class="button" style="display: inline-block; background: #10b981; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none;">
                    📦 View Orders
                </a>
            </li>
            <li style="margin-bottom: 8px;">
                <a href="/admin/vendors/vendorprofile/" class="button" style="display: inline-block; background: #f59e0b; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none;">
                    🏪 Manage Vendors
                </a>
            </li>
            <li>
                <a href="/admin/users/user/" class="button" style="display: inline-block; background: #8b5cf6; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none;">
                    👥 Manage Users
                </a>
            </li>
        </ul>
    </div>
    
    <!-- Recent Notifications Widget -->
    <div class="module">
        <h2>🔔 Recent Notifications</h2>
        <div style="padding: 12px;">
            {% if recent_notifications %}
                <ul style="list-style: none; padding: 0;">
                    {% for notification in recent_notifications %}
                        <li style="margin-bottom: 12px; padding: 8px; background: {% if not notification.is_read %}#eff6ff{% else %}#f9fafb{% endif %}; border-radius: 6px;">
                            <div style="display: flex; justify-content: space-between; align-items: start;">
                                <div style="flex: 1;">
                                    <strong>{{ notification.title }}</strong>
                                    <p style="margin: 4px 0; font-size: 12px; color: #6b7280;">{{ notification.message|truncatechars:60 }}</p>
                                    <small style="color: #9ca3af;">{{ notification.created_at|timesince }} ago</small>
                                </div>
                                {% if not notification.is_read %}
                                    <span style="background: #3b82f6; color: white; padding: 2px 6px; border-radius: 10px; font-size: 10px;">New</span>
                                {% endif %}
                            </div>
                        </li>
                    {% endfor %}
                </ul>
                <div style="margin-top: 12px; text-align: center;">
                    <a href="{% url 'notifications:list' %}" style="background: #3b82f6; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; display: inline-block;">
                        View All Notifications →
                    </a>
                </div>
            {% else %}
                <p style="color: #6b7280; text-align: center;">No notifications yet</p>
            {% endif %}
        </div>
    </div>
    
    <!-- System Status Widget -->
    <div class="module">
        <h2>⚙️ System Status</h2>
        <div style="padding: 12px;">
            <p><strong>Django Version:</strong> 5.2.13</p>
            <p><strong>Debug Mode:</strong> {% if debug %}Enabled{% else %}Disabled{% endif %}</p>
            <p><strong>Server Time:</strong> {% now "Y-m-d H:i:s" %}</p>
        </div>
    </div>
</div>
{% endblock %}
