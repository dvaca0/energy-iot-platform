"""Issue node credentials — ADR-0002 step 1.

    venv/bin/python3 -m app.db.provision_node list
    venv/bin/python3 -m app.db.provision_node issue N001
    venv/bin/python3 -m app.db.provision_node issue N001 --rotate

The plaintext token is printed **once** and never stored. Only its SHA-256 hash
goes into ``nodes.auth_token_hash``. Losing it means reissuing, which is
deliberate: a credential that can be recovered from the server is a credential
an attacker can recover from the server.

Issuing is refused for a node that already has one unless ``--rotate`` is given,
so a routine run cannot silently invalidate a working node's credential.
"""

from __future__ import annotations

import argparse
import sys

from app.db import node_auth
from app.db.database import SessionLocal
from app.db.models import Node


def cmd_list() -> int:
    session = SessionLocal()
    try:
        rows = session.query(Node).order_by(Node.code).all()
        print(f"{'node':6} {'commission':15} {'credential':12} issued")
        print("-" * 60)
        for node in rows:
            cred = "issued" if node.auth_token_hash else "NONE"
            issued = node.auth_token_issued_at or "-"
            print(f"{node.code:6} {node.commission_state:15} {cred:12} {issued}")
        missing = [n.code for n in rows if not n.auth_token_hash]
        if missing:
            print(f"\n{len(missing)} node(s) without a credential: {', '.join(missing)}")
            print("They cannot authenticate; enforcement would reject them.")
        return 0
    finally:
        session.close()


def cmd_issue(code: str, rotate: bool) -> int:
    session = SessionLocal()
    try:
        node = session.query(Node).filter(Node.code == code).first()
        if node is None:
            print(f"error: no node {code!r}", file=sys.stderr)
            return 2

        if node.auth_token_hash and not rotate:
            print(
                f"error: {code} already has a credential "
                f"(issued {node.auth_token_issued_at}). Use --rotate to replace it, "
                f"which invalidates the current one immediately.",
                file=sys.stderr,
            )
            return 3

        token = node_auth.issue_token(session, node)
        session.commit()

        print(f"node   : {node.code}")
        print(f"issued : {node.auth_token_issued_at}")
        print("token  : (shown once, store it now)\n")
        print(f"  {token}\n")
        print("Install on the node, readable only by the collector's user:")
        print(f"  NODE_AUTH_TOKEN={token}")
        print("and send it as:  Authorization: Bearer <token>")
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provision_node", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    issue = sub.add_parser("issue")
    issue.add_argument("code")
    issue.add_argument(
        "--rotate",
        action="store_true",
        help="replace an existing credential (invalidates it immediately)",
    )

    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list()
    if args.command == "issue":
        return cmd_issue(args.code, args.rotate)
    return 1


if __name__ == "__main__":
    sys.exit(main())
