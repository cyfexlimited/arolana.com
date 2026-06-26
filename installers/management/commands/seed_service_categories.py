from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from installers.models import ServiceCategory


CATEGORIES = [
    ("Audio Visual Installers", "audio visual, audiovisual, av system, display, projector, conference"),
    ("Projector Installers", "projector, projection, lumens, throw distance"),
    ("Conference Room Setup Engineers", "conference room, video conferencing, boardroom, meeting room, zoom room, teams room"),
    ("Smart Classroom Installers", "smart classroom, classroom technology, education display"),
    ("Interactive Board Installers", "interactive board, smart board, interactive display"),
    ("CCTV & Security Installers", "cctv, surveillance, security camera, nvr, dvr"),
    ("Access Control Engineers", "access control, door access, card reader"),
    ("Biometric System Installers", "biometric, fingerprint, attendance system"),
    ("Networking Engineers", "networking, network switch, ethernet, lan"),
    ("Fiber Optic Engineers", "fiber optic, fibre optic, optical cable"),
    ("Wi-Fi & Router Setup Engineers", "wifi, wi-fi, router, access point, wireless network"),
    ("Data Center Engineers", "data center, data centre, server rack, server"),
    ("Laptop Repair Engineers", "laptop, notebook computer, macbook"),
    ("Phone Repair Engineers", "phone, smartphone, mobile phone, iphone, android"),
    ("Tablet Repair Engineers", "tablet, ipad"),
    ("Printer & Copier Engineers", "printer, copier, photocopier, scanner"),
    ("POS Terminal Technicians", "pos terminal, point of sale"),
    ("Medical Equipment Engineers", "medical equipment, hospital equipment, patient monitor"),
    ("Laboratory Equipment Engineers", "laboratory equipment, lab equipment, microscope"),
    ("Dental Equipment Engineers", "dental equipment, dental chair"),
    ("Solar & Inverter Engineers", "solar, inverter, photovoltaic, pv panel"),
    ("UPS & Power Backup Engineers", "ups, power backup, battery backup"),
    ("Generator Technicians", "generator, genset"),
    ("Electrical Installation Engineers", "electrical, wiring, distribution board, breaker"),
    ("Smart Home Installers", "smart home, home automation, smart switch"),
    ("Home Cinema Installers", "home cinema, home theater, home theatre"),
    ("Sound System Installers", "sound system, speaker, amplifier, audio system"),
    ("Public Address System Installers", "public address, pa system, microphone, mixer"),
    ("LED Video Wall Installers", "led video wall, video wall, led display"),
    ("Digital Signage Installers", "digital signage, signage display, commercial display"),
    ("Intercom Installers", "intercom, video door phone"),
    ("Fire Alarm System Installers", "fire alarm, smoke detector, fire detection"),
    ("Automation Engineers", "automation, controller, plc"),
    ("Smart Building Engineers", "smart building, building management, bms"),
    ("Agricultural Equipment Technicians", "agricultural equipment, farm machinery"),
    ("Industrial Equipment Engineers", "industrial equipment, industrial machine"),
    ("Office Equipment Technicians", "office equipment, shredder, laminator"),
    ("Appliance Repair Technicians", "appliance, refrigerator, washing machine, microwave"),
    ("CCTV Maintenance Engineers", "cctv maintenance, surveillance maintenance"),
    ("General Electronics Repair Engineers", "electronics repair, electronic device"),
]


class Command(BaseCommand):
    help = "Seed Arolana service marketplace categories."

    def handle(self, *args, **options):
        default_dir = Path(settings.MEDIA_ROOT) / "defaults" / "service_categories"
        created = 0
        updated = 0
        for name, keywords in CATEGORIES:
            slug = slugify(name.replace("&", ""))
            category, was_created = ServiceCategory.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "description": f"Verified Arolana professionals for {name.lower()}, setup, repair, and maintenance.",
                    "matching_keywords": keywords,
                    "is_active": True,
                },
            )
            image_path = default_dir / f"{slug}.webp"
            if image_path.exists() and not category.image:
                with image_path.open("rb") as image_file:
                    category.image.save(image_path.name, File(image_file), save=True)
            created += int(was_created)
            updated += int(not was_created)
        self.stdout.write(self.style.SUCCESS(f"Service categories ready: {created} created, {updated} updated."))
