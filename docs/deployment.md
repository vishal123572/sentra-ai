# Deployment guide

## Desktop or demonstration laptop

Python 3.10+ and a current browser are sufficient. Extract the full folder and run `python3 run.py --demo` (Windows: `py -3 run.py --demo`). No package installation is needed. The app binds to 127.0.0.1 by default and creates `data/satsa.sqlite3`.

The fixed demo login is `examiner` / `SatSaDemo2026!`. For a database created by an older version, run `python3 manage.py reset-demo-password` (Windows: `py -3 manage.py reset-demo-password`). Closing the console stops the app. Launch it again with the same database path to preserve users and review decisions. Use `--port 8081` if 8080 is already occupied.

To begin without synthetic data, run `python3 run.py` on a fresh database path. Omitting `--demo` does not erase demo data already loaded.

## Internal controlled server

1. Transfer the source archive and an approved Python 3.10+ runtime into the controlled environment.
2. Create an unprivileged `satsa` operating-system user.
3. Install source under `/opt/satsa`, owned read-only by the service account.
4. Create `/var/lib/satsa` with write permission only for that account.
5. Set `SATSA_ADMIN_PASSWORD` to an operator-chosen password before first boot for a controlled deployment; the bundled default is a public demo credential. Bootstrap the database as the service account:

```bash
sudo -u satsa python3 /opt/satsa/run.py --database /var/lib/satsa/satsa.sqlite3
```

6. Stop the interactive process after recording the credentials. Install `deployment/satsa.service` under `/etc/systemd/system/`, then run `systemctl daemon-reload` and `systemctl enable --now satsa`.
7. Configure an internal TLS reverse proxy using `deployment/nginx.conf.example`, local certificate paths and your internal DNS name. Add `Environment=SATSA_SECURE_COOKIE=1` to the service for HTTPS clients and restart it.
8. Restrict access to the approved internal network. The HTTP app remains bound to loopback behind the proxy.

The service and proxy examples require operator adaptation and have not been executed in this build environment. The bundled HTTP server is adequate for a bounded local demonstration; production rollout needs a hardened serving strategy, concurrency/load testing and organisational security approval.

## Docker deployment

With Docker Compose available:

```bash
docker compose up --build -d
docker compose logs satsa
```

Open http://127.0.0.1:8080. A named volume preserves the database. The container runs as a non-root UID, drops capabilities and uses a read-only root filesystem. Its `/data` volume is writable. Startup creates only the first-run account and does not seed synthetic organisations. To load synthetic examples explicitly, sign in as administrator and use **Load demo** in the app. Repeating that action preserves existing assessments and examiner decisions.

Building needs access to the Python base image. For offline deployment, build on the preparation machine:

```bash
docker build -t satsa:1.3.0 .
docker save -o satsa-image.tar satsa:1.3.0
```

Transfer the tar into the controlled network:

```bash
docker load -i satsa-image.tar
docker compose up -d --no-build
```

No application network access is required at runtime. On 4 October 2026, the Docker CLI was installed, but `docker info` could not reach the Docker Desktop Linux engine (its named pipe was absent). Image build and container execution therefore did not run; test these templates on the target host.

## Backup and recovery

Use `python3 manage.py backup backups/assessment.sqlite3` for a consistent backup. Protect the backup because it contains accounts, exports, findings and reviews. Do not copy only the live SQLite main file while WAL writes are active.

To restore: stop the service, retain a backup of the current database, restore the consistent backup at the configured database path, remove stale WAL/SHM sidecars while stopped, restore restrictive permissions and start the service.

## Updates

Retain the database, transfer the reviewed source bundle and run the test suite before deployment. The new observation and comparison tables are created without deleting existing assessments; historic engine snapshots are covered by compatibility tests. Back up and validate on a copy before an operational upgrade. Source updates do not recompute historical assessments automatically.

## Planning estimates

A bounded desktop demonstration starts with 2 CPU cores, 4 GB RAM and 1 GB free space; retain additional space for original submissions and backups. These are estimates, not capacity certification. Python and a browser are the only application prerequisites; optional Node runs frontend integration checks. Operating work includes local account administration, export-completeness checks, periodic backups, review of detector changes and expert adjudication. Deployment cost and operator time depend on the institution's hardware, data volumes and assurance process; no measured production cost or installation-time guarantee is claimed.
