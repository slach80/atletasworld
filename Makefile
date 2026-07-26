.PHONY: dev dev-up dev-down migrate test test-fast test-dev dev-start dev-stop shell stripe-secret superuser

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

# ── CT315 dev server (192.168.1.235 on pve-05) ────────────────────────────────

# Start CT315 and run full test suite on it (mirrors CI environment)
test-dev:
	@echo "Starting CT315 atletasworld-dev..."
	ssh root@192.168.1.105 "pct start 315"
	@sleep 5
	@echo "Pulling latest code and running tests on CT315..."
	ssh root@192.168.1.105 "pct exec 315 -- /opt/atletasworld/run-tests.sh"
	@echo "Stopping CT315..."
	ssh root@192.168.1.105 "pct stop 315"

# Start CT315 for UI/UX testing — open http://192.168.1.235:8001
dev-start:
	@echo "Starting CT315 atletasworld-dev..."
	ssh root@192.168.1.105 "pct start 315"
	@sleep 5
	@echo "Pulling latest code..."
	ssh root@192.168.1.105 "pct exec 315 -- bash -c 'cd /opt/atletasworld && git pull origin main && venv/bin/pip install --quiet -r requirements.txt && cd src && ../venv/bin/python manage.py migrate --noinput'"
	@echo ""
	@echo "Dev server ready. Start it with:"
	@echo "  ssh root@192.168.1.105 'pct exec 315 -- /opt/atletasworld/dev-server.sh'"
	@echo "  Open: http://192.168.1.235:8001"
	@echo ""
	@echo "When done: make dev-stop"

# Stop CT315
dev-stop:
	ssh root@192.168.1.105 "pct stop 315 && echo CT315 stopped"

# ── Django shell ──────────────────────────────────────────────────────────────

# Django shell
shell:
	$(ENV) bash -c 'cd src && python manage.py shell'

# Create a superuser
superuser:
	$(ENV) bash -c 'cd src && python manage.py createsuperuser'
