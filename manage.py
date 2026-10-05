#!/usr/bin/env python3
"""Local administrator utilities. Custom passwords are entered interactively."""
import argparse
from contextlib import closing
import getpass
import sqlite3
import secrets
from pathlib import Path
from app.server import ROOT, DEFAULT_DEMO_PASSWORD
from app.storage import Store, now, password_hash


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", default=str(ROOT / "data" / "satsa.sqlite3"))
    sub = p.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup", help="Create a consistent SQLite backup, including while the app is running.")
    backup.add_argument("destination")
    reset = sub.add_parser("reset-password")
    reset.add_argument("username")
    demo_reset = sub.add_parser("reset-demo-password", help="Set an existing account to the fixed demo password.")
    demo_reset.add_argument("username", nargs="?", default="examiner")
    create = sub.add_parser("create-user")
    create.add_argument("username")
    create.add_argument("--role", choices=["admin", "examiner", "reader"], default="examiner")
    args = p.parse_args()
    if not Path(args.database).exists():
        p.error("Database does not exist. Start the app once first.")
    store = Store(args.database)
    if args.command == "backup":
        destination = Path(args.destination).resolve()
        if destination == Path(args.database).resolve() or destination.exists():
            p.error("Choose a new backup filename, different from the live database.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with store.connect() as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
        print(f"Consistent backup created: {destination}")
        return
    if args.command == "reset-demo-password":
        password = DEFAULT_DEMO_PASSWORD
    else:
        password = getpass.getpass("New password (10+ characters): ")
        if len(password) < 10 or len(password) > 512 or password != getpass.getpass("Confirm password: "):
            p.error("Passwords must match and contain 10–512 characters.")
    with store.transaction() as db:
        user = db.execute("SELECT * FROM users WHERE username=?", (args.username,)).fetchone()
        if args.command in {"reset-password", "reset-demo-password"}:
            if not user:
                p.error("Username does not exist.")
            db.execute("UPDATE users SET password=? WHERE id=?", (password_hash(password), user["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        else:
            if user or not 3 <= len(args.username) <= 60:
                p.error("Username already exists or is not 3–60 characters long.")
            db.execute("INSERT INTO users VALUES(?,?,?,?,?)", (secrets.token_hex(8), args.username, password_hash(password), args.role, now()))
        Store.audit(db, "local-admin", "account."+args.command, {"username": args.username})
    print("Account updated. Existing sessions were revoked after password reset.")
    if args.command == "reset-demo-password":
        print(f"Demo login: {args.username} / {DEFAULT_DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
