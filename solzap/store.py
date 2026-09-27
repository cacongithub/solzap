"""Persistência do kit em SQLite próprio (não mexe no banco do bot hospedeiro)."""
import secrets
import sqlite3
from contextlib import contextmanager
import threading
from decimal import Decimal

from solders.pubkey import Pubkey

from .payments import PaymentRequest

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    phone TEXT PRIMARY KEY,
    address TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS contacts (
    phone TEXT PRIMARY KEY,      -- normalizado (com DDI e o 9)
    wa_id TEXT NOT NULL          -- exatamente como o WhatsApp mandou; é para ele que se responde
);
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    sender_phone TEXT NOT NULL,
    recipient_phone TEXT NOT NULL,
    recipient_address TEXT NOT NULL,
    amount TEXT NOT NULL,
    mint TEXT NOT NULL,
    reference TEXT NOT NULL UNIQUE,
    memo TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | paid | expired
    signature TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    paid_at TEXT
);
"""


class Store:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commit/rollback
                yield conn
        finally:
            conn.close()

    # --- carteiras (telefone -> endereço público; o kit nunca guarda chaves privadas) ---
    def set_wallet(self, phone, address):
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO wallets (phone, address) VALUES (?, ?) "
                      "ON CONFLICT(phone) DO UPDATE SET address=excluded.address", (phone, address))

    def get_wallet(self, phone):
        with self._conn() as c:
            row = c.execute("SELECT address FROM wallets WHERE phone=?", (phone,)).fetchone()
        return row["address"] if row else None

    # --- identificador do WhatsApp por contato ---
    def remember_wa_id(self, phone, wa_id):
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO contacts (phone, wa_id) VALUES (?, ?) "
                      "ON CONFLICT(phone) DO UPDATE SET wa_id=excluded.wa_id", (phone, wa_id))

    def wa_id(self, phone):
        """Para onde mandar mensagem a este contato (o próprio número se ele nunca escreveu)."""
        with self._conn() as c:
            row = c.execute("SELECT wa_id FROM contacts WHERE phone=?", (phone,)).fetchone()
        return row["wa_id"] if row else phone

    # --- cobranças ---
    def add_payment(self, sender_phone, recipient_phone, request):
        pid = secrets.token_urlsafe(8)
        request.memo = request.memo or f"solzap:{pid}"
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO payments (id, sender_phone, recipient_phone, recipient_address, amount, mint, reference, memo) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (pid, sender_phone, recipient_phone, str(request.recipient), str(request.amount),
                 str(request.mint), str(request.reference), request.memo))
        return pid

    def get_payment(self, pid):
        with self._conn() as c:
            return c.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()

    def pending_payments(self):
        with self._conn() as c:
            return c.execute("SELECT * FROM payments WHERE status='pending' ORDER BY created_at").fetchall()

    def mark_paid(self, pid, signature):
        """True só para quem de fato mudou o status (evita comprovante duplicado)."""
        with self._lock, self._conn() as c:
            cur = c.execute("UPDATE payments SET status='paid', signature=?, paid_at=datetime('now') "
                            "WHERE id=? AND status='pending'", (signature, pid))
            return cur.rowcount == 1

    def expire_older_than(self, minutes):
        with self._lock, self._conn() as c:
            c.execute("UPDATE payments SET status='expired' WHERE status='pending' "
                      "AND created_at < datetime('now', ?)", (f"-{int(minutes)} minutes",))


def row_to_request(row):
    return PaymentRequest(
        recipient=Pubkey.from_string(row["recipient_address"]),
        amount=Decimal(row["amount"]),
        mint=Pubkey.from_string(row["mint"]),
        reference=Pubkey.from_string(row["reference"]),
        label="Remessa via WhatsApp",
        memo=row["memo"],
    )
