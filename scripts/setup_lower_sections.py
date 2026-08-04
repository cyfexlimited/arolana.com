from products.models import ProductListLowerSection, ProductListTrustBenefit

sections = [
    ("why_buy","Why Buy From Arolana",1,6,6,3,2,False),
    ("buying_guides","Buying Guides",2,24,6,3,2,False),
    ("recently_viewed","Recently Viewed",3,30,10,5,2,False),
    ("recommendations","You May Also Like",4,30,10,5,2,False),
    ("verified_providers","See Verified Service Providers",5,40,8,4,2,False),
    ("blog","From Our Blog",6,38,4,3,2,True),
]

for st,title,order,max_items,d,t,m,shuffle in sections:
    ProductListLowerSection.objects.update_or_create(
        section_type=st,
        defaults={
            "title": title,
            "display_order": order,
            "maximum_items": max_items,
            "desktop_visible_count": d,
            "tablet_visible_count": t,
            "mobile_visible_count": m,
            "shuffle_on_refresh": shuffle,
            "is_active": True,
        },
    )

why = ProductListLowerSection.objects.get(section_type="why_buy")

benefits = [
    ("Genuine Products","Shop approved products from trusted sellers.","fas fa-certificate",1),
    ("Verified Vendors","Buy from verified vendors and manufacturers.","fas fa-user-check",2),
    ("Secure Payments","Protected payments and safer transactions.","fas fa-lock",3),
    ("Fast Delivery","Reliable delivery options across supported locations.","fas fa-truck",4),
    ("Easy Returns","Clear return support for eligible purchases.","fas fa-undo-alt",5),
    ("Warranty Support","Warranty information and after-sales support.","fas fa-shield-alt",6),
]

for title,desc,icon,order in benefits:
    ProductListTrustBenefit.objects.update_or_create(
        section=why,
        title=title,
        defaults={
            "description": desc,
            "icon": icon,
            "display_order": order,
            "is_active": True,
        },
    )

print("✓ Default lower sections created.")
print("✓ Trust benefits created.")
