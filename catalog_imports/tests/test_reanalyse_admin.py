from unittest.mock import Mock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, SimpleTestCase

from catalog_imports.admin import ImportItemAdmin
from catalog_imports.models import ImportItem


class ReanalyseAdminTests(SimpleTestCase):
    def test_get_object_tool_runs_analysis_and_never_requires_post(self):
        request = RequestFactory().get('/admin/catalog_imports/importitem/7/reanalyse/')
        request.session = {}
        request._messages = FallbackStorage(request)

        item = Mock()
        item.pk = 7
        item.status = ImportItem.STATUS_BLOCKED
        item.hold_reason = 'source_price_unverified'
        item.error_message = ''

        model_admin = ImportItemAdmin(ImportItem, AdminSite())
        with patch('catalog_imports.admin.get_object_or_404', return_value=item), patch(
            'catalog_imports.admin.analyse_item'
        ) as analyse:
            response = model_admin.reanalyse_view(request, '7')

        analyse.assert_called_once_with(item)
        item.refresh_from_db.assert_called_once_with()
        self.assertEqual(response.status_code, 302)
        self.assertIn('#verification-state-tab', response['Location'])
