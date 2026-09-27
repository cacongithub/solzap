"""Operações de carteira usadas em testes e setup (em produção quem paga é a carteira do usuário)."""
import base64
import json
import time
from pathlib import Path

from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.system_program import CreateAccountParams, create_account
from solders.transaction import Transaction
import spl.token.instructions as tok
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.models import InitializeMintParams, MintToParams

from .transfer import transfer_instructions

MINT_SIZE = 82


def load_keypair(path):
    return Keypair.from_bytes(bytes(json.loads(Path(path).read_text())))


def save_keypair(kp, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(bytes(kp))))
    path.chmod(0o600)


def load_or_create(path):
    return load_keypair(path) if Path(path).exists() else _created(path)


def _created(path):
    kp = Keypair()
    save_keypair(kp, path)
    return kp


def send(rpc, instructions, payer, signers, confirm_timeout=60):
    blockhash = Hash.from_string(rpc.get_latest_blockhash())
    msg = Message.new_with_blockhash(instructions, payer.pubkey(), blockhash)
    tx = Transaction(list(signers), msg, blockhash)
    sig = rpc.send_transaction(base64.b64encode(bytes(tx)).decode())
    deadline = time.monotonic() + confirm_timeout
    while time.monotonic() < deadline:
        status = rpc.get_signature_status(sig)
        if status and status.get("confirmationStatus") in ("confirmed", "finalized"):
            if status.get("err"):
                raise RuntimeError(f"transação {sig} falhou: {status['err']}")
            return sig
        time.sleep(1.5)
    raise TimeoutError(f"transação {sig} não confirmou em {confirm_timeout}s")


def create_test_mint(rpc, authority, decimals=6):
    """Cria um token de teste (ex.: 'USDC de mentira') com `authority` como emissor."""
    mint = Keypair()
    rent = rpc.call("getMinimumBalanceForRentExemption", MINT_SIZE)
    ixs = [
        create_account(CreateAccountParams(from_pubkey=authority.pubkey(), to_pubkey=mint.pubkey(),
                                           lamports=rent, space=MINT_SIZE, owner=TOKEN_PROGRAM_ID)),
        tok.initialize_mint(InitializeMintParams(decimals=decimals, program_id=TOKEN_PROGRAM_ID,
                                                     mint=mint.pubkey(), mint_authority=authority.pubkey())),
    ]
    send(rpc, ixs, authority, [authority, mint])
    return mint.pubkey()


def mint_to(rpc, authority, mint, owner, raw_amount):
    ata = tok.get_associated_token_address(owner, mint)
    ixs = [
        tok.create_idempotent_associated_token_account(authority.pubkey(), owner, mint),
        tok.mint_to(MintToParams(program_id=TOKEN_PROGRAM_ID, mint=mint, dest=ata,
                                     mint_authority=authority.pubkey(), amount=raw_amount)),
    ]
    return send(rpc, ixs, authority, [authority])


def pay_request(rpc, payer, request, decimals=6):
    """Paga uma PaymentRequest do jeito que uma carteira Solana Pay faria."""
    return send(rpc, transfer_instructions(payer.pubkey(), request, decimals), payer, [payer])
