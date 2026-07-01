# Beetter Server

Central Flask API server for the Beetter platform. It serves as the single source of truth for user accounts and sensor data, consumed by the mobile app and synchronized with local Beetter-Home instances.

## Features

- REST API for sensor data ingestion and retrieval
- JWT-based authentication with account registration and login
- User management dashboard (admin)
- InfluxDB integration for time-series sensor data
- PostgreSQL for user and configuration data

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3 · Flask 3.0 |
| Database | PostgreSQL (user/config data) · InfluxDB (time-series sensor data) |
| Auth | JWT (PyJWT) · Flask-Login · Flask-Bcrypt |
| Frontend | Jinja2 templates (admin dashboard) |
| Deployment | Docker · Gunicorn |

## Getting Started

```bash
# Copy and fill in your environment variables
cp .env.example .env

# Start all services with Docker Compose
docker compose up -d
```

See [Beetter-Technical-Documentation](https://github.com/Projet-Beetter/Beetter-Technical-Documentation) for the full deployment guide.

## Project Structure

```
blueprints/
  api/          # Data ingestion and retrieval endpoints
  auth/         # Registration, login, JWT issuance
  dashboard/    # Admin user management views
  utils/
    influxdb.py # InfluxDB client helpers
models.py       # SQLAlchemy models
Dockerfile
compose.yml
```

## License

[CC BY-NC 4.0](LICENSE) — Projet Beetter, ESIEE Paris
