# Generated for Arolana admin-controlled product article reader

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0020_categoryarticlelink"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="productarticlelink",
            options={
                "ordering": ["sort_order", "-article__published_at"],
                "verbose_name": "Product Article Link",
                "verbose_name_plural": "Product Article Links",
            },
        ),
        migrations.AlterField(
            model_name="productarticlelink",
            name="open_behavior",
            field=models.CharField(
                choices=[
                    ("same_page", "Open in same page"),
                    ("new_page", "Open in new tab"),
                    ("popup", "Open in popup / modal"),
                    ("split_reader", "Open beside product / split reader"),
                ],
                default="same_page",
                help_text="Controls how this article opens from the product page.",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="productarticlelink",
            name="reader_content_mode",
            field=models.CharField(
                choices=[
                    ("clean_full_article", "Clean full article"),
                    ("full_article", "Full article page"),
                    ("body_only", "Article body only"),
                ],
                default="clean_full_article",
                help_text="Controls what content loads inside the split reader.",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="productarticlelink",
            name="reader_show_ads",
            field=models.BooleanField(
                default=False,
                help_text="Show article ads inside the product split reader.",
            ),
        ),
        migrations.AddField(
            model_name="productarticlelink",
            name="reader_show_cookie_banner",
            field=models.BooleanField(
                default=False,
                help_text="Show imported cookie/consent banners inside the product split reader.",
            ),
        ),
        migrations.AddField(
            model_name="productarticlelink",
            name="reader_show_chat_widgets",
            field=models.BooleanField(
                default=False,
                help_text="Show imported chat widgets inside the product split reader.",
            ),
        ),
        migrations.AddField(
            model_name="productarticlelink",
            name="reader_show_site_header_footer",
            field=models.BooleanField(
                default=False,
                help_text="Show imported site header/footer inside the product split reader.",
            ),
        ),
        migrations.AddField(
            model_name="productarticlelink",
            name="reader_show_newsletter",
            field=models.BooleanField(
                default=False,
                help_text="Show newsletter blocks inside the product split reader.",
            ),
        ),
        migrations.AddField(
            model_name="productarticlelink",
            name="reader_show_comments",
            field=models.BooleanField(
                default=True,
                help_text="Show comments inside the product split reader.",
            ),
        ),
        migrations.AddField(
            model_name="productarticlelink",
            name="reader_show_author_box",
            field=models.BooleanField(
                default=True,
                help_text="Show author box inside the product split reader.",
            ),
        ),
        migrations.AddField(
            model_name="productarticlelink",
            name="reader_show_share_box",
            field=models.BooleanField(
                default=True,
                help_text="Show share/social box inside the product split reader.",
            ),
        ),
    ]