from dataclasses import dataclass


@dataclass(frozen=True)
class PrivateUploadRequirement:
    model_label: str
    field_name: str
    policy_key: str

    @property
    def identity(self):
        return (self.model_label.lower(), self.field_name)


# Central policy contract for every currently protected private upload field.
#
# IMPORTANT:
# - Adding a private media authorization rule without adding a requirement here
#   is an audit failure.
# - Adding a private upload validator without an authorization rule is an audit
#   failure.
# - Adding a new FileField/ImageField under a known private upload root without
#   registering it is an audit failure.
EXPECTED_PRIVATE_UPLOADS = (
    PrivateUploadRequirement(
        "vendors.VendorProfile",
        "verification_documents",
        "KYC",
    ),
    PrivateUploadRequirement(
        "kyc.KYCDocument",
        "document_file",
        "KYC",
    ),
    PrivateUploadRequirement(
        "installers.ServiceProviderProfile",
        "cac_certificate_upload",
        "KYC",
    ),
    PrivateUploadRequirement(
        "installers.ServiceProviderProfile",
        "government_id_upload",
        "KYC",
    ),
    PrivateUploadRequirement(
        "installers.ProviderProfileChangeRequest",
        "proposed_file",
        "SENSITIVE_PROFILE_FILE",
    ),
    PrivateUploadRequirement(
        "installers.ProviderKYCDocument",
        "file",
        "KYC",
    ),
    PrivateUploadRequirement(
        "arolana_payments.PaymentTransaction",
        "manual_proof",
        "PAYMENT_PROOF",
    ),
    PrivateUploadRequirement(
        "chat.ChatMessage",
        "attachment",
        "CHAT_ATTACHMENT",
    ),
    PrivateUploadRequirement(
        "chat.VendorChatMessage",
        "attachment",
        "CHAT_ATTACHMENT",
    ),
    PrivateUploadRequirement(
        "smartchat.SmartChatMessage",
        "image",
        "CHAT_IMAGE",
    ),
    PrivateUploadRequirement(
        "smartchat.AIMessage",
        "image",
        "CHAT_IMAGE",
    ),
    PrivateUploadRequirement(
        "deliveries.DeliveryRequest",
        "proof_of_delivery",
        "PRIVATE_PROFILE_IMAGE",
    ),
    PrivateUploadRequirement(
        "deliveries.RiderProfile",
        "id_document",
        "RIDER_DOCUMENT",
    ),
    PrivateUploadRequirement(
        "deliveries.RiderProfile",
        "driver_license",
        "RIDER_DOCUMENT",
    ),
    PrivateUploadRequirement(
        "deliveries.RiderProfile",
        "vehicle_document",
        "RIDER_DOCUMENT",
    ),
    PrivateUploadRequirement(
        "deliveries.RiderProfile",
        "profile_photo",
        "PRIVATE_PROFILE_IMAGE",
    ),
    PrivateUploadRequirement(
        "deliveries.RiderProfile",
        "dashboard_image",
        "PRIVATE_PROFILE_IMAGE",
    ),
    PrivateUploadRequirement(
        "installers.ServiceQuoteRequest",
        "completion_photo",
        "PRIVATE_PROFILE_IMAGE",
    ),
    PrivateUploadRequirement(
        "pages.JobApplication",
        "resume",
        "RESUME",
    ),
    PrivateUploadRequirement(
        "products.ProductReview",
        "video_review",
        "REVIEW_VIDEO",
    ),
    PrivateUploadRequirement(
        "products.ReviewVideo",
        "video_file",
        "REVIEW_VIDEO",
    ),
    PrivateUploadRequirement(
        "products.ReviewVideo",
        "thumbnail",
        "PRIVATE_PROFILE_IMAGE",
    ),
    PrivateUploadRequirement(
        "mobile_customers.MobileCustomer",
        "profile_image",
        "PRIVATE_PROFILE_IMAGE",
    ),
)


EXPECTED_PRIVATE_UPLOAD_MAP = {
    requirement.identity: requirement
    for requirement in EXPECTED_PRIVATE_UPLOADS
}


EXPLICIT_PUBLIC_UPLOADS = frozenset({
    ("core.SiteSettings", "site_logo"),
    ("core.SiteSettings", "site_favicon"),
    ("core.SiteSettings", "footer_logo"),
    ("core.SiteSettings", "smart_chat_bot_image"),
    ("core.PromoBanner", "image"),
    ("core.HomePageAppearance", "desktop_background_image"),
    ("core.HomePageAppearance", "mobile_background_image"),
    ("accounts.User", "avatar"),
    ("accounts.UserProfile", "avatar"),
    ("vendors.VendorProfile", "store_logo"),
    ("vendors.VendorProfile", "store_banner"),
    ("vendors.VendorFactoryPhoto", "image"),
    ("products.Vendor", "shop_logo"),
    ("products.Vendor", "shop_banner"),

    ("products.Category", "image"),
    ("products.Category", "background_image"),

    ("products.Brand", "logo"),

    ("products.Product", "main_image"),
    ("products.Product", "local_video"),
    ("products.Product", "video_thumbnail"),
    ("products.Product", "manual_pdf"),
    
    ("products.Accessory", "image"),

    ("products.ProductImage", "image"),

    ("products.ProductVariant", "image"),
    ("products.ProductVariant", "hover_image"),
    ("products.ProductVariant", "manual_pdf"),
    ("products.ProductVariant", "local_video"),
    ("products.ProductVariant", "video_thumbnail"),

    ("products.ProductVariantImage", "image"),

    ("products.ProductVideo", "local_video"),
    ("products.ProductVideo", "thumbnail"),

    ("products.ProductReview", "review_video_converted"),

    ("products.ProductListingBanner", "background_image"),
    ("products.ProductListingBanner", "side_image"),
    ("installers.ServiceProviderProfile", "business_logo"),
    ("installers.ServiceProviderProfile", "business_banner"),
    ("installers.ServiceProviderProfile", "profile_image"),

    ("installers.ServiceCategory", "image"),

    (
        "installers.ServiceMarketplaceHomepageSection",
        "background_image",
    ),

    ("installers.ServicePortfolio", "image"),
    ("installers.ServicePortfolio", "local_video"),
    ("installers.ServicePortfolio", "video_thumbnail"),
    ("installers.ServiceProjectMedia", "image"),
    ("installers.ServiceProjectMedia", "video"),
    ("installers.ServiceProjectMedia", "processed_video"),
    ("installers.ServiceProjectMedia", "document"),
    ("installers.ServiceProjectMedia", "thumbnail"),
    ("landing_pages.LandingPage", "hero_background_image"),
    ("landing_pages.LandingPage", "hero_mobile_image"),
    ("landing_pages.LandingPage", "page_background_image"),
    ("landing_pages.LandingPage", "page_mobile_background_image"),
    ("landing_pages.LandingPage", "og_image"),
    ("landing_pages.LandingPageSection", "image"),
    ("landing_pages.LandingPageOffer", "image"),
    ("landing_pages.LandingPageCategoryCard", "image"),
    ("landing_pages.LandingPageTestimonial", "image"),
    ("landing_pages.LandingPageVideoGuide", "thumbnail"),
    ("blog.BlogCategory", "featured_image"),
    ("blog.BlogPost", "featured_image"),
    ("blog.BlogPost", "thumbnail_image"),
    ("blog.BlogPost", "local_video"),
    ("hero_banners.HeroBanner", "image_desktop"),
    ("hero_banners.HeroBanner", "image_tablet"),
    ("hero_banners.HeroBanner", "image_mobile"),
    ("ads.AdCreative", "image"),
    ("ads.AdCreative", "image_mobile"),
    ("ads.AdBanner", "image"),
    ("ads.AdBanner", "image_mobile"),
    ("ads.Advertisement", "image"),
    ("homepage.HomepageBannerImage", "image"),
    ("homepage.HomepageVideoSection", "local_video"),
    ("homepage.HomepageVideoSection", "poster_image"),
    ("newsletter.NewsletterCampaign", "hero_image"),
    ("newsletter.NewsletterCampaign", "product_image"),
    ("pages.SupportTopic", "image"),
    ("pages.SupportArticle", "image"),
    ("pages.FAQ", "image"),
    ("pages.HelpCenterHero", "background_image"),
    ("videos.Video", "video_file"),
    ("videos.Video", "custom_thumbnail"),
    ("videos.VideoGallery", "cover_image"),
    ("manufacturers.Manufacturer", "logo"),
    ("manufacturers.Manufacturer", "banner"),
    ("arolana_payments.ManualCryptoWallet", "qr_code"),
})

EXPLICIT_PUBLIC_UPLOAD_IDENTITIES = {
    (model_label.lower(), field_name)
    for model_label, field_name in EXPLICIT_PUBLIC_UPLOADS
}
