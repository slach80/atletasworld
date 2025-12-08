# Atletas World

Custom Django platform for Atletas World soccer training business.

## Features

### Client Portal
- Personal dashboard with upcoming sessions
- Manage player profiles (multiple children)
- Book training sessions with preferred coaches
- View packages, history, and assessments
- Receive coach notifications and progress reports

### Coach Portal (NEW)
- Dashboard with today's sessions and stats
- View all players trained with session history
- Set availability and manage schedule
- **Player Assessments**: Rate effort, technical, tactical, physical, and goals (1-5 scale)
- Quick assess multiple players per session
- Notify parents directly with custom messages
- Track attendance for each session

### User Management
- **Role-based access**: Coach, Client, and Admin groups
- Coaches created by admin (no self-signup)
- Clients register through signup process
- Automatic group assignment on registration

### Admin Features
- Full Django admin for all models
- Create and manage coach accounts
- Business analytics and reporting
- Payment and booking oversight

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

## Demo Credentials

### Coach Accounts (Coach Portal)
| Email | Password | Name |
|-------|----------|------|
| `mirko@atletasworld.com` | `coach123` | Mirko Trapletti |
| `roger@atletasworld.com` | `coach123` | Roger Espinoza |

### Client Accounts (Client Portal)
| Email | Password | Name |
|-------|----------|------|
| `testparent@example.com` | `demo123` | Test Parent |
| `john@example.com` | `demo123` | John Smith |

**Login URL:** http://localhost:8000/accounts/login/

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
