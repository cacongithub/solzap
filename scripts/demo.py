"""Demo de ponta a ponta: cobrança -> pagamento -> confirmação.

Uso:  python scripts/demo.py [valor]            (rede em SOLZAP_NETWORK, padrão devnet)
      SOLZAP_NETWORK=localnet python scripts/demo.py 25

Na primeira execução cria as carteiras em .keys/<rede>/. Na localnet pede SOL
sozinho; na devnet pede para usar faucet.solana.com. Usa um token próprio de
6 casas como "USDC de teste", para não depender do faucet da Circle.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solders.pubkey import Pubkey

from solzap import RPC, create_payment_request, wait_for_payment
from solzap.config import explorer_tx_url, network
from solzap.wallet import create_test_mint, load_or_create, mint_to, pay_request

KEYS_ROOT = Path(__file__).resolve().parents[1] / ".keys"
MIN_LAMPORTS = 50_000_000  # 0,05 SOL basta para dezenas de transações


def main(amount="25"):
    net = network()
    rpc = RPC(net["rpc"])
    KEYS = KEYS_ROOT / net["name"]
    payer = load_or_create(KEYS / "payer.json")
    merchant = load_or_create(KEYS / "merchant.json")

    lamports = rpc.get_balance(payer.pubkey())
    if lamports < MIN_LAMPORTS and net["name"] == "localnet":
        rpc.call("requestAirdrop", str(payer.pubkey()), 10 * 10**9)
        while (lamports := rpc.get_balance(payer.pubkey())) < MIN_LAMPORTS:
            time.sleep(0.5)
    if lamports < MIN_LAMPORTS:
        print(f"Carteira pagadora sem SOL de teste ({lamports / 1e9} SOL).")
        print(f"Abra https://faucet.solana.com, escolha devnet e envie 1 SOL para:\n\n  {payer.pubkey()}\n")
        print("Depois rode o script de novo.")
        return 1

    mint_file = KEYS / "mint.txt"
    if mint_file.exists():
        mint = Pubkey.from_string(mint_file.read_text().strip())
    else:
        print("Criando token de teste (dUSDC)...")
        mint = create_test_mint(rpc, payer)
        mint_file.write_text(str(mint))
        mint_to(rpc, payer, mint, payer.pubkey(), 1_000_000 * 10**6)
    print(f"Rede: {net['name']}  |  Token: {mint}")

    req = create_payment_request(merchant.pubkey(), amount, mint,
                                 label="solzap demo", message="Remessa de teste", memo="solzap-demo")
    print(f"\nCobrança criada:\n  {req.url}\n")

    print("Pagando como se fosse a carteira do cliente...")
    pay_request(rpc, payer, req)

    sig = wait_for_payment(rpc, req, timeout=90)
    print(f"Pagamento confirmado e validado: {amount} dUSDC")
    print(f"  {explorer_tx_url(sig, net['name'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
