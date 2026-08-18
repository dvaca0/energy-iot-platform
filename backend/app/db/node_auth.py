"""Node credential issuance and verification — ADR-0002 step 1.

Identity is a credential the node presents, never an attribute of the request.
Specifically **never the source address**: three nodes here share two public NAT
addresses, those addresses change, and on 2026-08-06 two different producers
published as ``N001`` from one address. Anything derived from the network path
is a hint, not an identity.

The token is generated once, shown once, and stored only as a SHA-256 hash. A
stolen database therefore yields no usable credential. Comparison is constant
time.

Three outcomes, deliberately distinct — collapsing them is how "who is this?"
and "may they write?" get conflated:

``AuthResult.authenticated``
    A credential was presented and matched a node.
``AuthResult.subject``
    Which node it matched. Compared against the *claimed* node code by the
    caller; a mismatch is an impersonation attempt, not an authentication
    failure.
``AuthResult.violation``
    Why it failed, recorded for the security trail.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Node

#: Presented as ``Authorization: Bearer <token>`` or ``X-Node-Token: <token>``.
TOKEN_BYTES = 32


@dataclass(frozen=True)
class AuthResult:
    """Outcome of authenticating one request."""

    authenticated: bool
    #: Node code the credential maps to, when it maps to one.
    subject: str | None = None
    #: unauthenticated | unknown_credential | ok
    violation: str | None = None

    @property
    def status(self) -> str:
        """Value stored in ``monitor_node_heartbeats.auth_status``."""
        if self.authenticated:
            return "authenticated"
        return self.violation or "unauthenticated"


def hash_token(token: str) -> str:
    """SHA-256 of a token. The only form ever persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """A fresh credential. Returned once; only its hash is stored."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def issue_token(session: Session, node: Node, *, now: datetime | None = None) -> str:
    """Issue (or rotate) a node's credential and return the plaintext once.

    Does not commit — the caller owns the transaction. Rotation is deliberate
    and immediate: the previous token stops working the moment this commits,
    so a compromised credential can be revoked by reissuing.
    """
    token = generate_token()
    node.auth_token_hash = hash_token(token)
    node.auth_token_issued_at = now or datetime.utcnow()
    return token


def extract_token(headers: Any) -> str | None:
    """Pull the credential out of a request's headers.

    Accepts ``Authorization: Bearer <t>`` and ``X-Node-Token: <t>``. The second
    exists because some edge HTTP clients on the fleet cannot set an
    Authorization header without also enabling other auth machinery.
    """
    auth = headers.get("authorization") or headers.get("Authorization")
    if auth:
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
    token = headers.get("x-node-token") or headers.get("X-Node-Token")
    return token.strip() if token and token.strip() else None


def authenticate(session: Session, token: str | None) -> AuthResult:
    """Resolve a presented credential to a node.

    Compares in constant time against every issued hash. The fleet is three
    nodes; if it ever becomes large this becomes an indexed lookup on the hash,
    which is equally safe because the hash is not a secret.
    """
    if not token:
        return AuthResult(False, violation="unauthenticated")

    presented = hash_token(token)

    for node in session.query(Node).filter(Node.auth_token_hash.isnot(None)).all():
        if hmac.compare_digest(node.auth_token_hash, presented):
            return AuthResult(True, subject=node.code, violation=None)

    return AuthResult(False, violation="unknown_credential")


def record_violation(
    session: Session,
    *,
    violation: str,
    claimed_node: str | None = None,
    auth_subject: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    producer: str | None = None,
    endpoint: str | None = None,
    detail: str | None = None,
) -> None:
    """Append to the append-only identity-violation record.

    Never raises: a failure to record evidence must not also fail the request
    that produced it, or the endpoint becomes trivially deniable.
    """
    try:
        session.execute(
            text(
                "INSERT INTO node_identity_violations "
                "  (claimed_node, auth_subject, violation, source_ip, "
                "   user_agent, producer, endpoint, detail) "
                "VALUES (:claimed, :subject, :violation, :ip, :ua, :prod, :ep, :detail)"
            ),
            {
                "claimed": claimed_node,
                "subject": auth_subject,
                "violation": violation,
                "ip": source_ip,
                "ua": (user_agent or "")[:200] or None,
                "prod": producer,
                "ep": endpoint,
                "detail": detail,
            },
        )
    except Exception:
        pass


def client_ip(request: Any) -> str | None:
    """Best-effort source address — for the record only, never for identity."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def enforcement_applies_to(node_code: str | None, config: Any = None) -> bool:
    """Whether a missing credential must be *refused* for this node.

    The single place ``node_auth.mode`` and ``node_auth.exempt_nodes`` are ever
    combined. Every caller asks this question and none re-derives it, because
    re-deriving it is exactly how the two halves of the policy came apart:

    Between 2026-08-06 and 2026-08-13 ``exempt_nodes: ["N003"]`` was honoured by
    ``/api/monitoring/heartbeat``, which consulted both fields, and ignored by
    both ingest paths, which passed only ``mode`` through as a bare boolean. The
    exemption therefore looked applied — heartbeats were accepted — while every
    one of N003's 5,958 measurement uploads was rejected 401 and its liveness
    silently froze. An exemption that holds on one route and not another is
    worse than no exemption: it is invisible.

    Returns True when the credential is mandatory. An exempt node still fails
    authentication and still records a violation; it is simply not refused, so
    ``security.unauthenticated_producer`` keeps the exemption visible.
    """
    if config is None:
        from app.monitoring.config import get_config

        config = get_config()

    auth = config.node_auth
    if not auth.enforcing:
        return False
    return node_code not in (auth.exempt_nodes or ())


__all__ = [
    "AuthResult",
    "authenticate",
    "client_ip",
    "enforcement_applies_to",
    "extract_token",
    "generate_token",
    "hash_token",
    "issue_token",
    "record_violation",
]
