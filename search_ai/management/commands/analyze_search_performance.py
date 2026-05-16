from django.core.management.base import BaseCommand
from django.db import models
from django.db.models import Count, Avg
from search_ai.models import SearchAnalytics, SearchHistory
from datetime import timedelta
from django.utils import timezone

class Command(BaseCommand):
    help = 'Analyze search performance and provide insights'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('SEARCH ANALYTICS REPORT'))
        self.stdout.write(self.style.SUCCESS('=' * 60))

        # Total searches
        total_searches = SearchHistory.objects.count()
        self.stdout.write(f'\n📊 Total Searches: {total_searches}')

        # Popular searches
        popular_searches = SearchHistory.objects.values('query').annotate(
            count=Count('id')
        ).order_by('-count')[:10]

        self.stdout.write('\n🔥 Top 10 Searches:')
        for i, search in enumerate(popular_searches, 1):
            self.stdout.write(f'   {i}. "{search["query"]}" - {search["count"]} searches')

        # Click-through rate by position
        clicks_by_position = SearchAnalytics.objects.values('position').annotate(
            total=Count('id'),
            clicks=Count('id', filter=models.Q(clicked=True)),
        ).order_by('position')

        self.stdout.write('\n📈 Click-Through Rate by Position:')
        for pos in clicks_by_position:
            ctr = (pos['clicks'] / pos['total'] * 100) if pos['total'] > 0 else 0
            self.stdout.write(f'   Position {pos["position"]}: {ctr:.1f}% ({pos["clicks"]}/{pos["total"]})')

        # Zero-result searches
        zero_results = SearchHistory.objects.filter(results_count=0).count()
        zero_percent = (zero_results / total_searches * 100) if total_searches > 0 else 0
        self.stdout.write(f'\n❌ Searches with no results: {zero_results} ({zero_percent:.1f}%)')

        self.stdout.write(self.style.SUCCESS('\n✅ Analysis complete!'))
