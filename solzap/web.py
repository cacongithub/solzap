"""Blueprint Flask: página de pagamento + endpoint "transaction request" do Solana Pay.

    app.register_blueprint(make_blueprint(store, rpc, net))

Rotas:
    GET  /pay/<id>               página que o link do WhatsApp abre
    GET  /pay/<id>/status        {"status": "pending|paid|expired", ...}
    GET  /api/solzap/tx/<id>     metadados (spec Solana Pay)
    POST /api/solzap/tx/<id>     {"account": "<pagador>"} -> {"transaction": "<base64>"}
    POST /api/solzap/submit/<id> {"transaction": "<assinada, base64>"} -> {"signature": ...}
"""
import base64
import io
from functools import lru_cache
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from flask import Blueprint, abort, jsonify, render_template_string, request, url_for
from markupsafe import Markup
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from .config import explorer_tx_url
from .rpc import RPCError
from .store import row_to_request
from .transfer import build_unsigned_transaction, mint_decimals
from .bot import mask_phone, money, short_address


def _qr_svg(data):
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Markup(buf.getvalue().decode())


def _external_url(endpoint, **values):
    """URL absoluta respeitando o proxy (Railway, Heroku, túneis): quem termina o TLS
    avisa em X-Forwarded-Proto; sem isso sairia http:// numa página https."""
    url = url_for(endpoint, _external=True, **values)
    if request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() == "https" and url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url


def make_blueprint(store, rpc, net, icon_url="", on_submitted=None):
    bp = Blueprint("solzap", __name__, static_folder="static", static_url_path="/solzap-static")
    decimals = lru_cache(maxsize=8)(lambda mint: mint_decimals(rpc, mint))

    def payment_or_404(pid):
        row = store.get_payment(pid)
        if row is None:
            abort(404)
        return row

    @bp.get("/pay/<pid>")
    def pay_page(pid):
        row = payment_or_404(pid)
        page_url = _external_url("solzap.pay_page", pid=pid)
        tx_url = _external_url("solzap.tx_request", pid=pid)  # absoluta: vai no QR, a carteira chama de fora
        origin = page_url.split("/pay/")[0]
        return render_template_string(
            PAGE,
            row=row,
            amount=money(row["amount"]),
            recipient=mask_phone(row["recipient_phone"]),
            address=short_address(row["recipient_address"]),
            network=net["name"],
            qr=_qr_svg(f"solana:{tx_url}"),
            phantom=f"https://phantom.app/ul/browse/{quote(page_url, safe='')}?ref={quote(origin, safe='')}",
            solflare=f"https://solflare.com/ul/v1/browse/{quote(page_url, safe='')}?ref={quote(origin, safe='')}",
            tx_url=url_for("solzap.tx_request", pid=pid),  # relativa: a página chama no mesmo protocolo
            submit_url=url_for("solzap.submit", pid=pid),
            status_url=url_for("solzap.pay_status", pid=pid),
            explorer=explorer_tx_url(row["signature"], net["name"]) if row["signature"] else "",
        )

    @bp.get("/pay/<pid>/status")
    def pay_status(pid):
        row = payment_or_404(pid)
        return jsonify(status=row["status"], signature=row["signature"],
                       explorer=explorer_tx_url(row["signature"], net["name"]) if row["signature"] else "")

    @bp.route("/api/solzap/tx/<pid>", methods=["GET", "POST", "OPTIONS"])
    def tx_request(pid):
        if request.method == "OPTIONS":
            return _cors(jsonify({}))
        row = payment_or_404(pid)
        if request.method == "GET":
            return _cors(jsonify(label="Remessa via WhatsApp", icon=icon_url))
        if row["status"] != "pending":
            return _cors(jsonify(error=f"cobrança {row['status']}")), 409
        account = (request.get_json(silent=True) or {}).get("account", "")
        try:
            payer = Pubkey.from_string(account)
        except ValueError:
            return _cors(jsonify(error="account inválida")), 400
        req = row_to_request(row)
        tx = build_unsigned_transaction(rpc, payer, req, decimals(str(req.mint)))
        return _cors(jsonify(transaction=tx,
                             message=f"US$ {money(req.amount)} para {mask_phone(row['recipient_phone'])}"))

    @bp.post("/api/solzap/submit/<pid>")
    def submit(pid):
        """Recebe a transação já assinada pela carteira e envia pela nossa RPC.

        Assim o pagamento não depende da RPC da carteira (a da Phantom na devnet cai com
        frequência). Só repassa transações que citam a reference desta cobrança.
        """
        row = payment_or_404(pid)
        if row["status"] != "pending":
            return jsonify(error=f"cobrança {row['status']}"), 409
        raw_b64 = (request.get_json(silent=True) or {}).get("transaction", "")
        try:
            tx = Transaction.from_bytes(base64.b64decode(raw_b64, validate=True))
        except Exception:
            return jsonify(error="transação inválida"), 400
        if Pubkey.from_string(row["reference"]) not in tx.message.account_keys:
            return jsonify(error="transação não corresponde à cobrança"), 400
        try:
            signature = rpc.send_transaction(raw_b64)
        except RPCError as e:
            return jsonify(error=str(e)[:300]), 502
        if on_submitted:
            on_submitted(pid)
        return jsonify(signature=signature)

    return bp


def _cors(resp):
    # Carteiras chamam o transaction request de fora do nosso domínio.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, ngrok-skip-browser-warning"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


PAGE = """<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pagar remessa</title>
<style>
  :root{--bg:#f6f7f9;--card:#fff;--text:#111827;--muted:#6b7280;--accent:#10b981;--accent-2:#059669;--border:#e5e7eb;--warn:#b45309}
  @media (prefers-color-scheme:dark){:root{--bg:#0b0f14;--card:#121821;--text:#e5e7eb;--muted:#9ca3af;--border:#1f2937;--warn:#f59e0b}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:24px 16px}
  .card{max-width:420px;margin:0 auto;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:24px}
  .amount{font-size:40px;font-weight:700;letter-spacing:-.02em;margin:4px 0}
  .muted{color:var(--muted);font-size:14px}
  .badge{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--border);color:var(--muted)}
  .btn{display:block;width:100%;text-align:center;padding:14px;border-radius:12px;border:0;font-weight:600;font-size:16px;text-decoration:none;cursor:pointer;margin-top:12px}
  .primary{background:var(--accent);color:#fff}.primary:hover{background:var(--accent-2)}
  .secondary{background:transparent;color:var(--text);border:1px solid var(--border)}
  .qr{background:#fff;border-radius:12px;padding:8px;margin:16px auto 0;max-width:240px}.qr svg{width:100%;height:auto;display:block}
  .status{margin-top:16px;padding:12px;border-radius:12px;border:1px solid var(--border);font-size:14px}
  .ok{border-color:var(--accent);color:var(--accent)} .err{color:var(--warn)}
  a.link{color:var(--accent)}
</style></head><body>
<main class="card" id="solzap" data-status="{{ row.status }}" data-tx-url="{{ tx_url }}"
      data-submit-url="{{ submit_url }}" data-status-url="{{ status_url }}">
  <span class="badge">Solana · {{ network }}</span>
  <p class="muted" style="margin:16px 0 0">Enviar para {{ recipient }}</p>
  <div class="amount">US$ {{ amount }}</div>
  <p class="muted" style="margin:0">em USDC · carteira de destino {{ address }}</p>

  <div id="pending" {% if row.status != 'pending' %}hidden{% endif %}>
    <button id="pay" class="btn primary" hidden>Pagar com esta carteira</button>
    <div id="open">
      <a class="btn primary" href="{{ phantom }}">Abrir na Phantom</a>
      <a class="btn secondary" href="{{ solflare }}">Abrir na Solflare</a>
      <p class="muted" style="text-align:center;margin:20px 0 0">Ou escaneie com a carteira em outro aparelho</p>
      <div class="qr">{{ qr }}</div>
    </div>
  </div>

  <div id="msg" class="status" {% if row.status == 'pending' %}hidden{% endif %}>
    {% if row.status == 'paid' %}<span class="ok">✅ Pagamento confirmado.</span> <a class="link" href="{{ explorer }}">Ver na blockchain</a>
    {% elif row.status == 'expired' %}<span class="err">Esta cobrança expirou. Peça um novo link no WhatsApp.</span>{% endif %}
  </div>
</main>
<script src="{{ url_for('solzap.static', filename='web3.iife.min.js') }}"></script>
<script src="{{ url_for('solzap.static', filename='pay.js') }}"></script>
</body></html>
"""
