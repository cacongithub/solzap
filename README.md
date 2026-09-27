# SolZap

**Send digital dollars through WhatsApp.** SolZap is an open-source kit that adds USDC payments on Solana to any WhatsApp bot. The first app built on it is a remittance flow: someone abroad types `send 50 to +55 11 91234-5678` in a chat, pays with any Solana wallet, and the family in Brazil gets USDC in seconds, with an on-chain receipt in the same chat.

> Built during the Colosseum **Crypto World's Fair** hackathon (Sep–Oct 2026). Solana track + Superteam Brasil track.

## Why

- **WhatsApp is where money conversations already happen in Brazil.** Nearly 150M people use it ([Statista](https://www.statista.com/topics/7731/whatsapp-in-brazil/)); businesses already sell, invoice and support customers there.
- **Brazilians abroad send money home through slow, expensive rails.** About 4.9M Brazilians live abroad ([Itamaraty, 2023](https://www.gov.br/mre/pt-br/assuntos/portal-consular/arquivos/comunidade-brasileira-no-exterior-estatisticas-2023)) and Brazil received about US$4.2B in personal transfers in 2025 ([Central Bank data](https://www.remessaonline.com.br/blog/remessas-internacionais-brasil-dados/)).
- **Stablecoins on Solana settle in seconds for a fraction of a cent.** The missing piece is the last mile: meeting people inside the app they already use, without asking them to learn crypto first.

SolZap is that last mile, packaged as a kit so any WhatsApp bot (not just ours) can add it.

What makes it different from other remittance apps: **nothing to install** (it lives inside WhatsApp, on the official Meta Cloud API), **non-custodial** (the wallet only signs; we never hold keys), and **reusable** (a kit for any bot, not a single app).

## Demo

| | |
|---|---|
| Live demo instance | https://solzap-demo-production.up.railway.app (devnet) |
| Payment from a real WhatsApp chat, paid with Phantom on iPhone | [devnet tx](https://explorer.solana.com/tx/49jrzxUq4PaxBajH6g7ZXTDtsLh1qzcrzpNg74A5fYtW2ssSVGDY4AKLUveafmLeecd1wAh46ehtQ1ZD8VawTpXF?cluster=devnet) |
| First end-to-end payment from a phone | [devnet tx](https://explorer.solana.com/tx/cw1Gh2Wwrz1yY6qsKnjG36uidJqigRCL8AyAm2DQ3aQYQmQq8n3ntFu9SSZrTEwUp2KQmChuQ9mP3E5FYb5vvv7?cluster=devnet) |

## How it works

```
 WhatsApp chat            SolZap (your bot's server)                 Solana
 ─────────────            ──────────────────────────                 ──────
 "carteira <address>" ──▶ store phone → wallet (public key only)
 "enviar 50 para +55…" ─▶ create payment request
                          (amount, USDC mint, recipient,
                           unique reference key)
            ◀── link ───  /pay/<id>  (opens inside Phantom/Solflare, or QR)
 wallet signs ──────────▶ build tx server-side, wallet only signs,
                          server relays it ─────────────────────────▶ transfer + memo
                          watcher finds tx by reference,             ◀── confirmed
                          validates amount / mint / recipient
 receipts to both   ◀──── "✅ sent" / "💰 you received" + explorer link
```

Key design choices:

- **Non-custodial.** SolZap never holds keys or funds. It stores public addresses and builds transactions that the payer's own wallet signs.
- **Solana Pay references.** Every payment request gets a unique reference key that is attached to the transfer, so the payment is found and validated on-chain without trusting the client.
- **The wallet signs, the server relays.** The pay page asks the wallet only to sign and relays through the bot's own RPC. Payments keep working even when the wallet's RPC is flaky (we hit this with devnet).
- **Strict validation.** A payment counts only if the transaction succeeded, references the request, moved the right token, and credited the recipient with at least the requested amount. The relay endpoint only accepts transactions that reference the payment being paid.
- **Drop-in for existing bots.** The kit has no opinion about your WhatsApp stack: `bot.handle(phone, text)` returns replies or `None` (not a payment command, continue your normal flow).
- **Works under strict Content-Security-Policy.** No inline scripts; everything is served from the host's own origin.

## Integrate in your bot

```python
from solzap import RPC
from solzap.bot import SolzapBot, receipt_replies
from solzap.config import explorer_tx_url, network
from solzap.store import Store
from solzap.watcher import Watcher
from solzap.web import make_blueprint

net = network("devnet")
rpc, store = RPC(net["rpc"]), Store("solzap.db")

def on_paid(row, signature):
    for r in receipt_replies(row, explorer_tx_url(signature, net["name"])):
        send_whatsapp(store.wa_id(r.to), r.text)          # your existing sender

watcher = Watcher(rpc, store, on_paid).start()
bot = SolzapBot(store, net["usdc"], base_url="https://yourbot.com",
                on_payment_created=lambda pid: watcher.poke())
app.register_blueprint(make_blueprint(store, rpc, net,           # your Flask app
                                      on_submitted=lambda pid: watcher.poke()))

# in your WhatsApp webhook:
replies = bot.handle(sender_phone, text)
if replies:
    for r in replies:
        send_whatsapp(store.wa_id(r.to), r.text)
else:
    ...  # not a payment command: your bot's normal flow
```

`store.wa_id()` answers to the exact id WhatsApp sent (Brazilian mobiles sometimes arrive without the 9th digit).

## Run it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                      # 16 tests

# Local validator (Solana CLI) + chat simulator, no Meta account needed:
solana-test-validator --reset &
SOLZAP_NETWORK=localnet .venv/bin/python scripts/demo.py 25        # one payment, end to end
SOLZAP_NETWORK=localnet .venv/bin/python scripts/simulator.py      # http://localhost:5055
```

On devnet, set `HELIUS_API_KEY` in `.env` (optional, public RPC works too) and use `SOLZAP_NETWORK=devnet`.

## Layout

| Path | What |
|---|---|
| `solzap/payments.py` | Solana Pay URLs, reference lookup, transfer validation |
| `solzap/transfer.py` | Server-side transaction builder (the wallet only signs) |
| `solzap/bot.py` | Chat commands, phone normalization, receipts |
| `solzap/store.py` | SQLite: wallets, payments, WhatsApp ids |
| `solzap/watcher.py` | Background confirmation, exactly-once receipts |
| `solzap/web.py`, `static/` | Pay page, Solana Pay transaction request, signed-tx relay |
| `scripts/` | End-to-end demo and WhatsApp chat simulator |

## Roadmap

1. **Pix off-ramp through a licensed partner**: the recipient chooses "keep in dollars" or "receive in reais via Pix". Conversion stays with a regulated partner; SolZap never converts or custodies.
2. **Mainnet with USDC**, per-user limits and monitoring.
3. **Wallet onboarding inside the chat** (embedded wallets), so recipients don't need to install anything.
4. **Merchant mode**: WhatsApp stores charging in USDC with the same kit.

## Team

Clériston Capistrano, solo founder from Brazil. Built [atendente.online](https://atendente.online) (AI customer service for WhatsApp), which is the first production bot SolZap plugs into. The atendente.online code predates the hackathon and is not part of this repository; SolZap was built during the hackathon.

## License

Apache-2.0 (see [LICENSE](LICENSE)). `solzap/static/web3.iife.min.js` is the unmodified build of [@solana/web3.js](https://github.com/solana-labs/solana-web3.js) (MIT), vendored so the pay page works under strict CSP.
