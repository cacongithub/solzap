"""Vigia em segundo plano: confirma cobranças pendentes na blockchain e avisa o hospedeiro."""
import logging
import threading

from .payments import PaymentError, PaymentNotFound, find_payment, validate_transfer
from .store import row_to_request

log = logging.getLogger("solzap.watcher")


class Watcher:
    def __init__(self, rpc, store, on_paid, interval=3.0, expire_minutes=30):
        self.rpc, self.store, self.on_paid = rpc, store, on_paid
        self.interval, self.expire_minutes = interval, expire_minutes
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="solzap-watcher", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._wake.set()

    def poke(self):
        """Acorda o vigia na hora (ex.: logo depois de criar uma cobrança)."""
        self._wake.set()

    def check_once(self):
        # Checa antes de expirar: um pagamento feito no último minuto não pode se perder.
        for row in self.store.pending_payments():
            request = row_to_request(row)
            try:
                signature = find_payment(self.rpc, request)
                validate_transfer(self.rpc, signature, request)
            except PaymentNotFound:
                continue
            except PaymentError as e:
                log.warning("cobrança %s: pagamento inválido (%s)", row["id"], e)
                continue
            except Exception:
                log.exception("cobrança %s: erro consultando a blockchain", row["id"])
                continue
            if self.store.mark_paid(row["id"], signature):
                try:
                    self.on_paid(self.store.get_payment(row["id"]), signature)
                except Exception:
                    log.exception("cobrança %s: erro no callback on_paid", row["id"])
        self.store.expire_older_than(self.expire_minutes)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:
                log.exception("erro no ciclo do vigia")
            self._wake.wait(self.interval)
            self._wake.clear()
