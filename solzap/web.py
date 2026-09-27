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


def make_blueprint(store, rpc, net, icon_url="", on_submitted=None):
    bp = Blueprint("solzap", __name__)
    decimals = lru_cache(maxsize=8)(lambda mint: mint_decimals(rpc, mint))

    def payment_or_404(pid):
        row = store.get_payment(pid)
        if row is None:
            abort(404)
        return row

    @bp.get("/pay/<pid>")
    def pay_page(pid):
        row = payment_or_404(pid)
        page_url = url_for("solzap.pay_page", pid=pid, _external=True)
        tx_url = url_for("solzap.tx_request", pid=pid, _external=True)
        origin = request.host_url.rstrip("/")
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
            tx_url=tx_url,
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
<main class="card">
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
<script src="https://cdn.jsdelivr.net/npm/@solana/web3.js@1.98.0/lib/index.iife.min.js"></script>
<script>
const provider = window.phantom?.solana || window.solflare || window.solana;
const $ = id => document.getElementById(id);
function show(html, cls){ const m=$('msg'); m.hidden=false; m.innerHTML='<span class="'+(cls||'')+'">'+html+'</span>'; }

async function poll(){
  const r = await fetch({{ status_url|tojson }}, {headers:{'ngrok-skip-browser-warning':'1'}}).then(r=>r.json()).catch(()=>null);
  if(r && r.status==='paid'){ $('pending').hidden=true; show('✅ Pagamento confirmado. <a class="link" href="'+r.explorer+'">Ver na blockchain</a>','ok'); return; }
  if(r && r.status==='expired'){ $('pending').hidden=true; show('Esta cobrança expirou. Peça um novo link no WhatsApp.','err'); return; }
  setTimeout(poll, 2500);
}

async function pay(){
  $('pay').disabled = true;
  try{
    const {publicKey} = await provider.connect();
    const res = await fetch({{ tx_url|tojson }}, {method:'POST', headers:{'Content-Type':'application/json','ngrok-skip-browser-warning':'1'},
                                                  body: JSON.stringify({account: publicKey.toString()})});
    const body = await res.json();
    if(!res.ok) throw new Error(body.error || 'erro ao montar a transação');
    const bytes = Uint8Array.from(atob(body.transaction), c => c.charCodeAt(0));
    const tx = solanaWeb3.Transaction.from(bytes);
    show('Assinando…');
    if(provider.signTransaction){
      const signed = await provider.signTransaction(tx);
      const raw = btoa(String.fromCharCode(...signed.serialize()));
      show('Enviando…');
      const sub = await fetch({{ submit_url|tojson }}, {method:'POST', headers:{'Content-Type':'application/json','ngrok-skip-browser-warning':'1'},
                                                        body: JSON.stringify({transaction: raw})});
      const sb = await sub.json();
      if(!sub.ok) throw new Error(sb.error || 'erro ao enviar');
    } else {
      await provider.signAndSendTransaction(tx);
    }
    show('Enviado. Aguardando confirmação na blockchain…');
  }catch(e){ show('Não foi possível pagar: '+(e.message||e),'err'); $('pay').disabled=false; }
}

if({{ (row.status == 'pending')|tojson }}){
  if(provider){ $('open').hidden=true; $('pay').hidden=false; $('pay').onclick=pay; }
  poll();
}
</script>
</body></html>
"""
