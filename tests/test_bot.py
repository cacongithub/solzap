from decimal import Decimal

import pytest
from solders.keypair import Keypair

from solzap.bot import SolzapBot, money, normalize_phone, parse_amount, receipt_replies
from solzap.store import Store

MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
MARIA, JOAO = "5511911112222", "351912345678"


@pytest.fixture
def bot(tmp_path):
    return SolzapBot(Store(str(tmp_path / "t.db")), MINT, base_url="https://bot.test/")


def test_normalize_phone():
    assert normalize_phone("+55 (11) 91111-2222") == MARIA
    assert normalize_phone("11 91111-2222") == MARIA
    assert normalize_phone("551187654321") == "5511987654321"  # formato antigo do WhatsApp, sem o 9
    assert normalize_phone("+351 912 345 678") == JOAO


def test_parse_amount_and_money():
    assert parse_amount("12,40") == Decimal("12.40")
    assert parse_amount("1.234,56") == Decimal("1234.56")
    assert parse_amount("50") == Decimal("50")
    assert parse_amount("12,345") is None and parse_amount("0") is None and parse_amount("abc") is None
    assert money("1234.5") == "1.234,50"


def test_non_commands_fall_through(bot):
    assert bot.handle(JOAO, "oi, qual o horário de funcionamento?") is None


def test_full_flow(bot):
    wallet = str(Keypair().pubkey())
    [r] = bot.handle(JOAO, "enviar 50 para +55 11 91111-2222")
    assert "ainda não cadastrou" in r.text and r.to == JOAO

    [r] = bot.handle(MARIA, f"carteira {wallet}")
    assert "cadastrada" in r.text
    assert bot.store.get_wallet(MARIA) == wallet

    [r] = bot.handle(JOAO, "Mande US$ 12,40 dólares pra 11 91111-2222")
    assert "US$ 12,40" in r.text and "https://bot.test/pay/" in r.text
    pid = r.text.split("/pay/")[1].split()[0]
    row = bot.store.get_payment(pid)
    assert (row["sender_phone"], row["recipient_phone"], row["recipient_address"], row["amount"], row["status"]) == \
           (JOAO, MARIA, wallet, "12.40", "pending")
    assert row["memo"] == f"solzap:{pid}"

    assert bot.store.mark_paid(pid, "sig1") is True
    assert bot.store.mark_paid(pid, "sig1") is False  # não duplica comprovante
    to_sender, to_recipient = receipt_replies(bot.store.get_payment(pid), "https://explorer/tx/sig1")
    assert to_sender.to == JOAO and to_recipient.to == MARIA and "US$ 12,40" in to_recipient.text


def test_rejections(bot):
    bot.handle(MARIA, f"carteira {Keypair().pubkey()}")
    assert "não parece" in bot.handle(MARIA, "carteira " + "z" * 44)[0].text  # base58 mas não cabe em 32 bytes
    assert "limite" in bot.handle(JOAO, "enviar 5000 para 11 91111-2222")[0].text
    assert "próprio" in bot.handle(MARIA, "enviar 5 para 11 91111-2222")[0].text
    assert "valor" in bot.handle(JOAO, "enviar 1,999 para 11 91111-2222")[0].text


def test_replies_go_to_original_wa_id(bot):
    [r] = bot.handle("551187654321", "ajuda")  # WhatsApp mandou sem o 9
    assert r.to == "5511987654321"
    assert bot.store.wa_id(r.to) == "551187654321"
    assert bot.store.wa_id("5511000000000") == "5511000000000"  # nunca escreveu


def test_self_send_only_when_allowed(tmp_path):
    bot = SolzapBot(Store(str(tmp_path / "s.db")), MINT, "https://bot.test", allow_self_send=True)
    bot.handle(MARIA, f"carteira {Keypair().pubkey()}")
    [r] = bot.handle(MARIA, "enviar 5 para 11 91111-2222")
    assert "/pay/" in r.text
