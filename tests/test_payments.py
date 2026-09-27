from decimal import Decimal

import pytest
from solders.keypair import Keypair

from solzap import (PaymentInvalid, PaymentNotFound, create_payment_request, find_payment,
                    parse_payment_url, validate_transfer)

MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
RECIPIENT = str(Keypair().pubkey())


def make_req(amount="12.5", memo=""):
    return create_payment_request(RECIPIENT, amount, MINT, label="Loja do Zé", message="Pedido #7", memo=memo)


def balance(owner, raw, idx=1, mint=MINT):
    return {"accountIndex": idx, "mint": mint, "owner": owner,
            "uiTokenAmount": {"amount": str(raw), "decimals": 6}}


def fake_tx(req, pre, post, err=None, include_reference=True):
    keys = [{"pubkey": str(Keypair().pubkey())}]
    if include_reference:
        keys.append({"pubkey": str(req.reference)})
    return {"transaction": {"message": {"accountKeys": keys}},
            "meta": {"err": err, "preTokenBalances": pre, "postTokenBalances": post}}


class FakeRPC:
    def __init__(self, tx=None, sigs=()):
        self.tx, self.sigs = tx, list(sigs)

    def get_transaction(self, signature):
        return self.tx

    def get_signatures_for_address(self, address, limit=10):
        return self.sigs


def test_url_has_solana_pay_fields():
    req = make_req("12.50", memo="remessa-42")
    assert req.url.startswith(f"solana:{RECIPIENT}?amount=12.5&spl-token={MINT}&reference={req.reference}")
    assert "label=Loja%20do%20Z%C3%A9" in req.url and "memo=remessa-42" in req.url


def test_url_roundtrip():
    req = make_req("0.000001", memo="x")
    back = parse_payment_url(req.url)
    assert (back.recipient, back.amount, back.mint, back.reference, back.label, back.memo) == \
           (req.recipient, req.amount, req.mint, req.reference, req.label, req.memo)


def test_amount_formatting_and_raw():
    assert "amount=1000&" in make_req("1000.00").url
    assert make_req("12.5").raw_amount(6) == 12_500_000
    with pytest.raises(ValueError):
        make_req("0.0000001").raw_amount(6)
    with pytest.raises(ValueError):
        make_req("-1")


def test_validate_ok_including_new_token_account():
    req = make_req("12.5")
    tx = fake_tx(req, pre=[], post=[balance(RECIPIENT, 12_500_000)])
    assert validate_transfer(FakeRPC(tx), "sig", req) is tx


def test_validate_rejects_short_payment():
    req = make_req("12.5")
    tx = fake_tx(req, pre=[balance(RECIPIENT, 1_000_000)], post=[balance(RECIPIENT, 13_000_000)])
    with pytest.raises(PaymentInvalid, match="menor"):
        validate_transfer(FakeRPC(tx), "sig", req)


def test_validate_rejects_wrong_mint_failed_tx_and_missing_reference():
    req = make_req("1")
    other_mint = str(Keypair().pubkey())
    with pytest.raises(PaymentInvalid):
        validate_transfer(FakeRPC(fake_tx(req, [], [balance(RECIPIENT, 10**6, mint=other_mint)])), "s", req)
    with pytest.raises(PaymentInvalid, match="falhou"):
        validate_transfer(FakeRPC(fake_tx(req, [], [balance(RECIPIENT, 10**6)], err={"x": 1})), "s", req)
    with pytest.raises(PaymentInvalid, match="reference"):
        validate_transfer(FakeRPC(fake_tx(req, [], [balance(RECIPIENT, 10**6)], include_reference=False)), "s", req)


def test_find_payment_skips_failed_and_picks_oldest():
    req = make_req()
    rpc = FakeRPC(sigs=[{"signature": "new", "err": None}, {"signature": "old", "err": None},
                        {"signature": "bad", "err": {"x": 1}}])
    assert find_payment(rpc, req) == "old"
    with pytest.raises(PaymentNotFound):
        find_payment(FakeRPC(sigs=[{"signature": "bad", "err": {"x": 1}}]), req)
