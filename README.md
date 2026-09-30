# Property Flow

A property-management revenue dashboard. Clients review revenue for the properties they manage. The frontend is a React app and the API is served alongside it with Docker Compose.

The assignment in `ASSIGNMENT.md` is to investigate revenue totals that do not match client records, figures that appear to belong to another company after a refresh, and totals that drift by fractions of a cent.

## Run

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs
