# Atletas World

Custom Django platform for Atletas World soccer training business.

## Features

- **Client Portal**: Personal accounts, booking history, progress tracking
- **Coach Dashboard**: Schedule management, client info, performance stats
- **Booking System**: Integrated scheduling with Google Calendar sync
- **Payment Processing**: Stripe integration with full revenue tracking
- **Analytics Dashboard**: Business intelligence and reporting
- **Review System**: Automated reviews and testimonials

## Project Structure

```
atletasworld/
├── src/                     # Django source code
│   ├── atletasworld/        # Main Django project
│   ├── clients/             # Client management app
│   ├── coaches/             # Coach management app
│   ├── bookings/            # Booking/scheduling app
│   ├── payments/            # Stripe payment processing
│   ├── analytics/           # Business analytics
│   └── reviews/             # Review system
├── static/                  # Static files (CSS, JS, images)
├── templates/               # HTML templates
├── media/                   # User uploaded files
├── public/                  # Public assets
├── resources/               # Shared resources (git submodule)
├── requirements.txt         # Python dependencies
└── .github/workflows/       # CI/CD pipelines
```

## Setup

### 1. Clone the repository

```bash
git clone --recurse-submodules https://github.com/slach80/atletasworld.git
cd atletasworld
```

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env with your configuration
```

### 5. Run migrations

```bash
cd src
python manage.py migrate
```

### 6. Create superuser

```bash
python manage.py createsuperuser
```

### 7. Run development server

```bash
python manage.py runserver
```

Visit http://localhost:8000/admin to access the admin panel.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key | - |
| `DEBUG` | Debug mode | `False` |
| `DATABASE_URL` | Database connection string | `sqlite:///db.sqlite3` |
| `STRIPE_PUBLIC_KEY` | Stripe publishable key | - |
| `STRIPE_SECRET_KEY` | Stripe secret key | - |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook secret | - |

## Shared Resources

The `resources/` directory is a git submodule linking to [share-resources](https://github.com/slach80/share-resources).

### Update shared resources

```bash
git submodule update --remote resources
git add resources
git commit -m "Update shared-resources submodule"
git push
```

## Development

### Running tests

```bash
cd src
python manage.py test
```

### Using shared scripts

```bash
./resources/scripts/build.sh
./resources/scripts/deploy.sh
```

## Deployment

The project uses GitHub Actions for CI/CD. On push to `main`:

1. Runs tests with PostgreSQL
2. Collects static files
3. Deploys to production

See `.github/workflows/deploy.yml` for details.

## Documentation

- [Platform Comparison](resources/docs/platform_comparison.md) - Detailed comparison with current Squarespace setup
- [Setup Guide](resources/docs/setup-guide.md) - Shared resources setup guide
