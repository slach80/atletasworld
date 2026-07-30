"""
Management command to create Stripe Products/Prices for Fall Program installment plans
and set up the corresponding Package DB records.

Usage:
    python manage.py setup_fall_subscriptions          # dry run — prints what would happen
    python manage.py setup_fall_subscriptions --live   # actually creates Stripe objects + saves DB
"""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.conf import settings


FALL_START = datetime.date(2026, 8, 17)
FALL_END   = datetime.date(2026, 11, 8)

# Existing pay-in-full packages (already in prod DB)
BASE_PACKAGES = [
    {'name': 'Elite 24 Fall',  'db_name': 'Elite 24 Fall',  'program_group': 'Elite 24 Fall'},
    {'name': 'Unlimited Fall', 'db_name': 'Unlimited Fall', 'program_group': 'Unlimited Fall'},
]

# Installment options to create
# interval_count: 1 = monthly (3 charges), 2 = every 2 months / "half" (2 charges)
INSTALLMENT_OPTIONS = [
    {
        'suffix': '— Monthly',
        'billing_tier': 'monthly',
        'interval': 'month',
        'interval_count': 1,
        'prices': {
            'Elite 24 Fall':  16000,   # $160.00 × 3 = $480
            'Unlimited Fall': 33400,   # $334.00 × 3 = $1002 (~full price)
        },
        'display_prices': {
            'Elite 24 Fall':  Decimal('160.00'),
            'Unlimited Fall': Decimal('334.00'),
        },
    },
    {
        'suffix': '— Half',
        'billing_tier': 'half',
        'interval': 'month',
        'interval_count': 2,
        'prices': {
            'Elite 24 Fall':  24000,   # $240.00 × 2 = $480
            'Unlimited Fall': 50000,   # $500.00 × 2 = $1000
        },
        'display_prices': {
            'Elite 24 Fall':  Decimal('240.00'),
            'Unlimited Fall': Decimal('500.00'),
        },
    },
]


class Command(BaseCommand):
    help = 'Set up Fall Program subscription packages (Stripe Products/Prices + DB records)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--live',
            action='store_true',
            help='Actually create Stripe objects and save DB records (default: dry run)',
        )

    def handle(self, *args, **options):
        live = options['live']
        if not live:
            self.stdout.write(self.style.WARNING('DRY RUN — pass --live to execute\n'))

        from clients.models import Package

        for base_info in BASE_PACKAGES:
            group = base_info['program_group']

            # Fetch existing pay-in-full package
            try:
                base_pkg = Package.objects.get(name=base_info['db_name'])
            except Package.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Base package '{base_info['db_name']}' not found in DB — skipping"))
                continue

            self.stdout.write(f"\n=== {group} (base pk={base_pkg.pk}, ${base_pkg.price}) ===")

            # Set program_group on the existing pay-in-full package
            if base_pkg.program_group != group:
                self.stdout.write(f"  SET program_group='{group}' on pk={base_pkg.pk} ({base_pkg.name})")
                if live:
                    base_pkg.program_group = group
                    base_pkg.save(update_fields=['program_group'])

            # Get or create Stripe Product
            stripe_product_id = self._get_or_create_stripe_product(base_pkg, group, live)

            # Create installment Package records
            for opt in INSTALLMENT_OPTIONS:
                pkg_name = f"{group} {opt['suffix']}"
                price_cents = opt['prices'][group]
                display_price = opt['display_prices'][group]
                billing_tier = opt['billing_tier']

                existing = Package.objects.filter(name=pkg_name).first()

                if existing and existing.stripe_price_id:
                    self.stdout.write(f"  SKIP {pkg_name} — already has stripe_price_id={existing.stripe_price_id}")
                    continue

                # Create Stripe Price
                stripe_price_id = self._create_stripe_price(
                    product_id=stripe_product_id,
                    pkg_name=pkg_name,
                    price_cents=price_cents,
                    interval=opt['interval'],
                    interval_count=opt['interval_count'],
                    live=live,
                )

                self.stdout.write(
                    f"  {'CREATE' if not existing else 'UPDATE'} Package: {pkg_name} | "
                    f"${display_price} | {billing_tier} | stripe_price_id={stripe_price_id}"
                )

                if live:
                    pkg_defaults = dict(
                        package_type=base_pkg.package_type,
                        description=base_pkg.description,
                        price=display_price,
                        sessions_included=base_pkg.sessions_included,
                        validity_weeks=base_pkg.validity_weeks,
                        is_active=True,
                        is_purchasable=True,
                        is_special=False,
                        event_start_date=FALL_START,
                        event_end_date=FALL_END,
                        billing_tier=billing_tier,
                        stripe_price_id=stripe_price_id or '',
                        program_group=group,
                    )
                    if existing:
                        for k, v in pkg_defaults.items():
                            setattr(existing, k, v)
                        existing.save()
                        self.stdout.write(self.style.SUCCESS(f"    Updated pk={existing.pk}"))
                    else:
                        new_pkg = Package.objects.create(name=pkg_name, **pkg_defaults)
                        self.stdout.write(self.style.SUCCESS(f"    Created pk={new_pkg.pk}"))

        if live:
            self.stdout.write(self.style.SUCCESS('\nDone. Run the Django check and verify in Stripe Dashboard.'))
        else:
            self.stdout.write(self.style.WARNING('\nDry run complete. Re-run with --live to apply.'))

    def _get_or_create_stripe_product(self, base_pkg, group, live):
        """Return a Stripe product ID for this program group, creating if needed."""
        if not settings.STRIPE_SECRET_KEY:
            self.stdout.write(self.style.WARNING('  STRIPE_SECRET_KEY not set — skipping Stripe product creation'))
            return 'prod_DRY_RUN'

        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY

        # Search for existing product by metadata
        try:
            results = stripe.Product.search(query=f'metadata["program_group"]:"{group}"')
            if results.data:
                product = results.data[0]
                self.stdout.write(f"  Found existing Stripe Product: {product.id} ({product.name})")
                return product.id
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Product search failed: {e}"))

        self.stdout.write(f"  CREATE Stripe Product: {group}")
        if not live:
            return 'prod_DRY_RUN'

        product = stripe.Product.create(
            name=group,
            description=f'APC Fall Program 2026 — {group} (Aug 17 – Nov 8)',
            metadata={'program_group': group},
        )
        self.stdout.write(self.style.SUCCESS(f"  Created product {product.id}"))
        return product.id

    def _create_stripe_price(self, product_id, pkg_name, price_cents, interval, interval_count, live):
        """Create a recurring Stripe Price and return its ID."""
        if not settings.STRIPE_SECRET_KEY:
            return 'price_DRY_RUN'

        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY

        self.stdout.write(
            f"    CREATE Stripe Price: ${price_cents/100:.2f} / {interval_count} {interval}(s) "
            f"under product {product_id}"
        )
        if not live:
            return 'price_DRY_RUN'

        price = stripe.Price.create(
            product=product_id,
            unit_amount=price_cents,
            currency='usd',
            recurring={'interval': interval, 'interval_count': interval_count},
            metadata={'package_name': pkg_name},
        )
        self.stdout.write(self.style.SUCCESS(f"    Created price {price.id}"))
        return price.id
