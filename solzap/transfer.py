"""Monta a transação de pagamento de uma cobrança (sem assinar).

É a mesma transação que uma carteira Solana Pay montaria: cria a conta de token do
destinatário se faltar, grava o memo e transfere com a reference anexada. O servidor
monta, a carteira do pagador só assina e envia.
"""
import base64

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction
import spl.token.instructions as tok
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.models import TransferCheckedParams

MEMO_PROGRAM_ID = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")


def mint_decimals(rpc, mint):
    info = rpc.get_account_info(mint)
    if not info:
        raise ValueError(f"token {mint} não existe nesta rede")
    return info["data"]["parsed"]["info"]["decimals"]


def transfer_instructions(payer, request, decimals):
    payer = Pubkey.from_string(str(payer))
    source = tok.get_associated_token_address(payer, request.mint)
    dest = tok.get_associated_token_address(request.recipient, request.mint)
    transfer = tok.transfer_checked(TransferCheckedParams(
        program_id=TOKEN_PROGRAM_ID, source=source, mint=request.mint, dest=dest,
        owner=payer, amount=request.raw_amount(decimals), decimals=decimals))
    # A spec do Solana Pay manda anexar a reference como conta somente-leitura na transferência.
    transfer = Instruction(transfer.program_id, transfer.data,
                           list(transfer.accounts) + [AccountMeta(request.reference, False, False)])
    ixs = [tok.create_idempotent_associated_token_account(payer, request.recipient, request.mint)]
    if request.memo:
        ixs.append(Instruction(MEMO_PROGRAM_ID, request.memo.encode(), []))
    ixs.append(transfer)
    return ixs


def build_unsigned_transaction(rpc, payer, request, decimals=None):
    """Transação serializada em base64, sem assinaturas, pronta para a carteira assinar."""
    decimals = mint_decimals(rpc, request.mint) if decimals is None else decimals
    payer = Pubkey.from_string(str(payer))
    blockhash = Hash.from_string(rpc.get_latest_blockhash())
    msg = Message.new_with_blockhash(transfer_instructions(payer, request, decimals), payer, blockhash)
    return base64.b64encode(bytes(Transaction.new_unsigned(msg))).decode()
