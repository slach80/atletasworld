.PHONY: dev dev-up dev-down migrate test shell stripe-secret

# Start all backing services (Postgres, Redis, Mailhog, Stripe CLI)
dev-up:
	docker compose -f docker-compose.dev.yml up -d
	@echo ""
	@echo "Services running:"
	@echo "  Postgres  → localhost:5432"
	@echo "  Redis     → localhost:6379"
	@echo "  Mailhog   → http://localhost:8025"
	@echo "  Stripe    → forwarding to localhost:8000/payments/webhook/"
	@echo ""
	@echo "Next: copy .env.dev to .env, update STRIPE_WEBHOOK_SECRET, then:"
	@echo "  make migrate && make dev"

# Stop all backing services
dev-down:
	docker compose -f docker-compose.dev.yml down

ENV=DATABASE_URL=postgres://atletasworld:atletasworld@localhost:5433/atletasworld_dev \
    SECRET_KEY=dev-secret-key-not-for-production \
    DEBUG=True \
    PYTHONPATH=src

# Run Django dev server
dev:
	$(ENV) cd src && python manage.py runserver

# Run migrations against dev DB
migrate:
	$(ENV) bash -c 'cd src && python manage.py migrate --noinput'

# Run full test suite against dev DB
test:
	$(ENV) python3 -m pytest src --tb=short -q

# Run tests and stop at first failure
test-fast:
	$(ENV) python3 -m pytest src --tb=short -q -x

# Print the Stripe webhook secret from the running stripe-cli container
stripe-secret:
	@docker compose -f docker-compose.dev.yml logs stripe-cli 2>&1 | grep "webhook signing secret" | tail -1

# Django shell
shell:
	$(ENV) bash -c 'cd src && python manage.py shell'

# Create a superuser
superuser:
	$(ENV) bash -c 'cd src && python manage.py createsuperuser'
