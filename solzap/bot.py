"""Tratador de conversa independente de framework.

    bot = SolzapBot(store, mint="...", base_url="https://meubot.com")
    replies = bot.handle(phone, text)   # None = não é comando do kit, siga o fluxo normal
    for r in replies: enviar_whatsapp(r.to, r.text)
"""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from solders.pubkey import Pubkey

from .payments import create_payment_request

BASE58 = r"[1-9A-HJ-NP-Za-km-z]{32,44}"
RE_WALLET = re.compile(rf"^(?:minha\s+)?carteira\s*[:\-]?\s*({BASE58})$", re.I)
RE_SHOW_WALLET = re.compile(r"^(?:minha\s+)?carteira\??$", re.I)
RE_SEND = re.compile(
    r"^(?:enviar|envia|envie|mandar|manda|mande|transferir)\s+"
    r"(?:us\$|u\$|\$|usd|usdc)?\s*([\d.,]+)\s*(?:d[oó]lar(?:es)?|usdc|usd)?\s+"
    r"(?:para|pra|pro|p/)\s+(.+)$",
    re.I,
)
RE_HELP = re.compile(r"^(?:ajuda|remessa|menu|help|dolar|dólar)\??$", re.I)


@dataclass
class Reply:
    to: str
    text: str


def normalize_phone(raw):
    """Só dígitos, com DDI. Celular BR sem o 9 (formato antigo que o WhatsApp às vezes usa) ganha o 9."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) in (10, 11):  # número BR sem DDI
        digits = "55" + digits
    if digits.startswith("55") and len(digits) == 12 and digits[4] in "6789":
        digits = digits[:4] + "9" + digits[4:]
    return digits


def parse_amount(text):
    text = text.strip()
    if "," in text:  # formato BR: 1.234,56
        text = text.replace(".", "").replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if value <= 0 or value != value.quantize(Decimal("0.01")):
        return None  # só positivos com até 2 casas (centavos)
    return value


def money(value):
    """12.4 -> '12,40'; 1234.5 -> '1.234,50' (exibição para o usuário)."""
    text = f"{Decimal(value):,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def mask_phone(phone):
    if phone.startswith("55") and len(phone) == 13:
        return f"+55 ({phone[2:4]}) •••••-{phone[-4:]}"
    return f"número final {phone[-4:]}" if len(phone) >= 8 else phone


def short_address(addr):
    return f"{addr[:4]}…{addr[-4:]}"


HELP = (
    "💸 *Remessa em dólar digital (USDC)*\n\n"
    "1️⃣ Quem recebe cadastra a carteira Solana dela:\n"
    "   _carteira SEU_ENDEREÇO_\n\n"
    "2️⃣ Quem envia manda:\n"
    "   _enviar 50 para +55 11 91234-5678_\n\n"
    "Você recebe um link para pagar pela carteira (Phantom, Solflare…). "
    "Quando o pagamento cai na blockchain, os dois recebem o comprovante aqui."
)


class SolzapBot:
    def __init__(self, store, mint, base_url, max_amount=Decimal("1000"), on_payment_created=None):
        self.store = store
        self.mint = str(mint)
        self.base_url = base_url.rstrip("/")
        self.max_amount = Decimal(max_amount)
        self.on_payment_created = on_payment_created

    def handle(self, phone, text):
        """Respostas com `to` normalizado; envie para store.wa_id(reply.to)."""
        wa_id, phone = phone, normalize_phone(phone)
        self.store.remember_wa_id(phone, re.sub(r"\D", "", wa_id))
        text = " ".join((text or "").split())
        if RE_HELP.match(text):
            return [Reply(phone, HELP)]
        if m := RE_WALLET.match(text):
            return self._register_wallet(phone, m.group(1))
        if RE_SHOW_WALLET.match(text):
            addr = self.store.get_wallet(phone)
            msg = (f"Sua carteira cadastrada: `{addr}`" if addr
                   else "Você ainda não cadastrou carteira. Envie: _carteira SEU_ENDEREÇO_")
            return [Reply(phone, msg)]
        if m := RE_SEND.match(text):
            return self._send(phone, m.group(1), m.group(2))
        return None

    def _register_wallet(self, phone, address):
        try:
            Pubkey.from_string(address)
        except ValueError:
            return [Reply(phone, "Esse endereço não parece uma carteira Solana válida. Confira e envie de novo.")]
        self.store.set_wallet(phone, address)
        return [Reply(phone, f"✅ Carteira `{short_address(address)}` cadastrada. "
                             "Agora qualquer pessoa pode te enviar dólar digital pelo seu número.")]

    def _send(self, sender, amount_text, recipient_text):
        amount = parse_amount(amount_text)
        if amount is None:
            return [Reply(sender, "Não entendi o valor. Exemplo: _enviar 50 para +55 11 91234-5678_")]
        if amount > self.max_amount:
            return [Reply(sender, f"Por enquanto o limite por envio é de US$ {money(self.max_amount)}.")]
        recipient = normalize_phone(recipient_text)
        if len(recipient) < 12:
            return [Reply(sender, "Não entendi o número de quem recebe. Use com DDD, ex.: +55 11 91234-5678")]
        if recipient == sender:
            return [Reply(sender, "Você não pode enviar para o seu próprio número.")]
        address = self.store.get_wallet(recipient)
        if not address:
            return [Reply(sender,
                          f"{mask_phone(recipient)} ainda não cadastrou uma carteira. 📲 Peça para a pessoa "
                          "mandar para este número:\n_carteira ENDEREÇO_SOLANA_\n\nDepois é só repetir o envio.")]
        request = create_payment_request(address, amount, self.mint, label="Remessa via WhatsApp",
                                         message=f"Envio para {mask_phone(recipient)}")
        pid = self.store.add_payment(sender, recipient, request)
        if self.on_payment_created:
            self.on_payment_created(pid)
        link = f"{self.base_url}/pay/{pid}"
        return [Reply(sender,
                      f"🧾 Envio de *US$ {money(amount)}* para {mask_phone(recipient)}\n"
                      f"Carteira de destino: `{short_address(address)}`\n\n"
                      f"Pague por aqui (vale por 30 min):\n{link}\n\n"
                      "Assim que confirmar na blockchain eu te mando o comprovante.")]


def receipt_replies(row, explorer_url):
    """Comprovante para quem enviou e para quem recebeu, depois da confirmação na blockchain."""
    amount = money(row["amount"])
    proof = f"🔗 Comprovante na blockchain:\n{explorer_url}"
    return [
        Reply(row["sender_phone"],
              f"✅ Envio confirmado! *US$ {amount}* chegaram para {mask_phone(row['recipient_phone'])}.\n\n{proof}"),
        Reply(row["recipient_phone"],
              f"💰 Você recebeu *US$ {amount}* em dólar digital (USDC) de {mask_phone(row['sender_phone'])}.\n"
              f"O valor já está na sua carteira `{short_address(row['recipient_address'])}`.\n\n{proof}"),
    ]
