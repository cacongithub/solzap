"""Cobranças em token SPL (USDC) via Solana Pay, com confirmação na blockchain.

Fluxo:
    req = create_payment_request(recipient, "12.50", mint, label="Loja X")
    req.url                      -> link solana: para a carteira (ou QR code)
    sig = wait_for_payment(rpc, req)   -> assinatura confirmada e validada

Cada cobrança leva uma chave "reference" única. A carteira inclui essa chave na
transação, e é por ela que encontramos o pagamento sem depender de webhook.
"""
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlencode, urlparse, parse_qs

from solders.keypair import Keypair
from solders.pubkey import Pubkey


class PaymentError(Exception):
    pass


class PaymentNotFound(PaymentError):
    pass


class PaymentInvalid(PaymentError):
    pass


def _parse_amount(amount):
    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        raise ValueError(f"valor inválido: {amount!r}")
    if value <= 0:
        raise ValueError("o valor precisa ser positivo")
    return value


def format_amount(value):
    """Decimal sem notação científica nem zeros à direita, como pede a spec do Solana Pay."""
    text = format(value.normalize(), "f")
    return text


@dataclass
class PaymentRequest:
    recipient: Pubkey
    amount: Decimal
    mint: Pubkey
    reference: Pubkey = field(default_factory=lambda: Keypair().pubkey())
    label: str = ""
    message: str = ""
    memo: str = ""

    @property
    def url(self):
        params = {"amount": format_amount(self.amount), "spl-token": str(self.mint), "reference": str(self.reference)}
        for key in ("label", "message", "memo"):
            if getattr(self, key):
                params[key] = getattr(self, key)
        return f"solana:{self.recipient}?{urlencode(params, quote_via=quote)}"

    def raw_amount(self, decimals):
        raw = self.amount * (Decimal(10) ** decimals)
        if raw != raw.to_integral_value():
            raise ValueError(f"{self.amount} tem mais casas decimais que o token ({decimals})")
        return int(raw)


def create_payment_request(recipient, amount, mint, label="", message="", memo=""):
    return PaymentRequest(
        recipient=Pubkey.from_string(str(recipient)),
        amount=_parse_amount(amount),
        mint=Pubkey.from_string(str(mint)),
        label=label,
        message=message,
        memo=memo,
    )


def parse_payment_url(url):
    """Inverso de PaymentRequest.url (usado pelo pagador de teste e por integrações)."""
    parsed = urlparse(url)
    if parsed.scheme != "solana":
        raise ValueError("não é um link solana:")
    qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    if "spl-token" not in qs:
        raise ValueError("o kit só trata cobranças em token SPL")
    req = create_payment_request(parsed.path, qs["amount"], qs["spl-token"],
                                 qs.get("label", ""), qs.get("message", ""), qs.get("memo", ""))
    req.reference = Pubkey.from_string(qs["reference"])
    return req


def find_payment(rpc, request):
    """Assinatura mais antiga bem-sucedida que cita a reference; PaymentNotFound se não houver."""
    sigs = rpc.get_signatures_for_address(request.reference, limit=20)
    ok = [s for s in sigs if s.get("err") is None]
    if not ok:
        raise PaymentNotFound(str(request.reference))
    return ok[-1]["signature"]


def _account_keys(tx):
    keys = tx["transaction"]["message"]["accountKeys"]
    return [k["pubkey"] if isinstance(k, dict) else k for k in keys]


def _owner_balance(balances, owner, mint):
    return sum(int(b["uiTokenAmount"]["amount"]) for b in balances
               if b.get("owner") == owner and b.get("mint") == mint)


def _decimals(tx, mint):
    for b in tx["meta"].get("postTokenBalances") or []:
        if b.get("mint") == mint:
            return b["uiTokenAmount"]["decimals"]
    raise PaymentInvalid("a transação não movimentou esse token")


def validate_transfer(rpc, signature, request):
    """Confere se a transação pagou o valor certo, no token certo, ao destinatário certo."""
    tx = rpc.get_transaction(signature)
    if tx is None:
        raise PaymentNotFound(signature)
    if tx["meta"].get("err") is not None:
        raise PaymentInvalid(f"transação falhou: {tx['meta']['err']}")
    if str(request.reference) not in _account_keys(tx):
        raise PaymentInvalid("a transação não contém a reference da cobrança")

    mint, owner = str(request.mint), str(request.recipient)
    pre = _owner_balance(tx["meta"].get("preTokenBalances") or [], owner, mint)
    post = _owner_balance(tx["meta"].get("postTokenBalances") or [], owner, mint)
    expected = request.raw_amount(_decimals(tx, mint))
    if post - pre < expected:
        raise PaymentInvalid(f"valor recebido {post - pre} menor que o esperado {expected}")
    return tx


def wait_for_payment(rpc, request, timeout=300, interval=2.0):
    """Faz polling até achar e validar o pagamento. Retorna a assinatura."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            signature = find_payment(rpc, request)
            validate_transfer(rpc, signature, request)
            return signature
        except PaymentNotFound:
            if time.monotonic() >= deadline:
                raise
            time.sleep(interval)
