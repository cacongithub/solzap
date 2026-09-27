"""Redes e tokens suportados."""
import os
from pathlib import Path


def _load_dotenv(path=Path(__file__).resolve().parents[1] / ".env"):
    """Lê KEY=valor de solzap/.env sem sobrescrever o que já está no ambiente."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

HELIUS_RPC = {"devnet": "https://devnet.helius-rpc.com/?api-key={}",
              "mainnet": "https://mainnet.helius-rpc.com/?api-key={}"}

NETWORKS = {
    "localnet": {
        "rpc": "http://127.0.0.1:8899",  # solana-test-validator
        "usdc": "",  # não existe USDC local; o demo cria um token de teste
        "explorer_suffix": "?cluster=custom&customUrl=http%3A%2F%2Flocalhost%3A8899",
    },
    "devnet": {
        "rpc": "https://api.devnet.solana.com",
        "usdc": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",  # USDC de teste da Circle
        "explorer_suffix": "?cluster=devnet",
    },
    "mainnet": {
        "rpc": "https://api.mainnet-beta.solana.com",
        "usdc": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "explorer_suffix": "",
    },
}


def network(name=None):
    name = name or os.getenv("SOLZAP_NETWORK", "devnet")
    cfg = dict(NETWORKS[name])
    cfg["name"] = name
    helius_key = os.getenv("HELIUS_API_KEY", "").strip()
    if helius_key and name in HELIUS_RPC:
        cfg["rpc"] = HELIUS_RPC[name].format(helius_key)
    cfg["rpc"] = os.getenv("SOLZAP_RPC_URL", cfg["rpc"])
    cfg["usdc"] = os.getenv("SOLZAP_MINT", cfg["usdc"])
    return cfg


def explorer_tx_url(signature, net=None):
    return f"https://explorer.solana.com/tx/{signature}{network(net)['explorer_suffix']}"
