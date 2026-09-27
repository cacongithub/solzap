"""Simulador local: dois "celulares" de WhatsApp falando com o bot, sem precisar da Meta.

Uso:  SOLZAP_NETWORK=localnet python scripts/simulator.py   ->  http://localhost:5055

Na localnet o botão "Pagar (carteira de teste)" paga a cobrança com a carteira
de .keys/localnet/payer.json, fazendo o papel da Phantom.
"""
import os
import sys
import threading
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, render_template_string, request
from werkzeug.middleware.proxy_fix import ProxyFix
from solders.pubkey import Pubkey

from solzap import RPC
from solzap.bot import SolzapBot, normalize_phone, receipt_replies
from solzap.config import explorer_tx_url, network
from solzap.store import Store, row_to_request
from solzap.wallet import load_keypair, pay_request
from solzap.watcher import Watcher
from solzap.web import make_blueprint

net = network()
rpc = RPC(net["rpc"])
keys = ROOT / ".keys" / net["name"]
mint = net["usdc"] or (keys / "mint.txt").read_text().strip()
store = Store(str(ROOT / f"solzap-{net['name']}.db"))

inbox = defaultdict(list)  # telefone -> [{"from": "me|bot", "text": ...}]
inbox_lock = threading.Lock()


def deliver(replies):
    with inbox_lock:
        for r in replies:
            inbox[r.to].append({"from": "bot", "text": r.text})


def on_paid(row, signature):
    deliver(receipt_replies(row, explorer_tx_url(signature, net["name"])))


watcher = Watcher(rpc, store, on_paid, interval=2).start()
bot = SolzapBot(store, mint, base_url=os.getenv("SOLZAP_BASE_URL", "http://localhost:5055"), on_payment_created=lambda pid: watcher.poke())

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # atrás de túnel HTTPS
app.register_blueprint(make_blueprint(store, rpc, net, on_submitted=lambda pid: watcher.poke()))


@app.post("/sim/send")
def sim_send():
    if not os.getenv("SOLZAP_BASE_URL"):
        bot.base_url = request.host_url.rstrip("/")  # usa o endereço por onde o simulador foi aberto
    phone = normalize_phone(request.json["phone"])
    text = request.json["text"]
    with inbox_lock:
        inbox[phone].append({"from": "me", "text": text})
    replies = bot.handle(phone, text)
    deliver(replies or [type("R", (), {"to": phone, "text": "🤖 (aqui entraria a IA do atendente.online)"})()])
    return jsonify(ok=True)


@app.get("/sim/inbox/<phone>")
def sim_inbox(phone):
    with inbox_lock:
        return jsonify(inbox[normalize_phone(phone)])


@app.post("/sim/pay/<pid>")
def sim_pay(pid):
    if net["name"] != "localnet":
        return jsonify(error="só na localnet"), 400
    row = store.get_payment(pid)
    sig = pay_request(rpc, load_keypair(keys / "payer.json"), row_to_request(row))
    watcher.poke()
    return jsonify(signature=sig)


@app.get("/")
def home():
    return render_template_string(PAGE, network=net["name"],
                                  test_wallet=str(load_keypair(keys / "merchant.json").pubkey()))


PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Simulador WhatsApp</title>
<style>
 :root{--bg:#eae6df;--panel:#f0f2f5;--me:#d9fdd3;--bot:#fff;--text:#111b21;--muted:#667781;--accent:#00a884}
 @media (prefers-color-scheme:dark){:root{--bg:#0b141a;--panel:#202c33;--me:#005c4b;--bot:#202c33;--text:#e9edef;--muted:#8696a0}}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif;padding:16px}
 h1{font-size:16px;margin:0 0 4px} .muted{color:var(--muted);font-size:12px}
 .phones{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-top:12px}
 .phone{background:var(--panel);border-radius:14px;display:flex;flex-direction:column;height:560px;overflow:hidden}
 .head{padding:10px 14px;font-weight:600;border-bottom:1px solid rgba(0,0,0,.08)}
 .msgs{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:6px;background:var(--bg)}
 .b{max-width:85%;padding:6px 10px;border-radius:8px;white-space:pre-wrap;word-break:break-word}
 .me{align-self:flex-end;background:var(--me)} .bot{align-self:flex-start;background:var(--bot)}
 .b a{color:var(--accent)} .b button{margin-top:6px;border:0;background:var(--accent);color:#fff;padding:6px 10px;border-radius:6px;cursor:pointer}
 form{display:flex;gap:8px;padding:10px} input{flex:1;padding:10px;border-radius:20px;border:0;background:var(--bot);color:var(--text)}
 form button{border:0;background:var(--accent);color:#fff;border-radius:20px;padding:0 16px;cursor:pointer}
 code{font-size:12px;word-break:break-all}
</style></head><body>
<h1>Simulador de WhatsApp · solzap · {{ network }}</h1>
<div class="muted">Carteira de teste para cadastrar: <code>{{ test_wallet }}</code></div>
<div class="phones">
  <div class="phone" data-phone="5511911112222"><div class="head">📱 Maria (Brasil) · +55 11 91111-2222</div><div class="msgs"></div>
    <form><input placeholder="Mensagem" value="carteira {{ test_wallet }}"><button>Enviar</button></form></div>
  <div class="phone" data-phone="351912345678"><div class="head">📱 João (Portugal) · +351 912 345 678</div><div class="msgs"></div>
    <form><input placeholder="Mensagem" value="enviar 50 para +55 11 91111-2222"><button>Enviar</button></form></div>
</div>
<script>
const esc = s => s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function render(text){
  let h = esc(text).replace(/\\*(.+?)\\*/g,'<b>$1</b>').replace(/_(.+?)_/g,'<i>$1</i>').replace(/`(.+?)`/g,'<code>$1</code>')
    .replace(/(https?:\\/\\/\\S+)/g,'<a href="$1" target="_blank">$1</a>');
  const m = text.match(/\\/pay\\/([\\w-]+)/);
  if(m && {{ (network == 'localnet')|tojson }}) h += '<br><button onclick="simPay(\\''+m[1]+'\\', this)">Pagar (carteira de teste)</button>';
  return h;
}
async function simPay(pid, btn){ btn.disabled=true; btn.textContent='Pagando…';
  const r = await fetch('/sim/pay/'+pid,{method:'POST'}).then(r=>r.json()); btn.textContent = r.error ? r.error : 'Pago ✔'; }
document.querySelectorAll('.phone').forEach(el => {
  const phone = el.dataset.phone, box = el.querySelector('.msgs'); let n = 0;
  el.querySelector('form').onsubmit = async e => { e.preventDefault(); const i = el.querySelector('input');
    if(!i.value.trim()) return; await fetch('/sim/send',{method:'POST',headers:{'Content-Type':'application/json','ngrok-skip-browser-warning':'1'},
      body: JSON.stringify({phone, text:i.value})}); i.value=''; };
  setInterval(async () => { const msgs = await fetch('/sim/inbox/'+phone,{headers:{'ngrok-skip-browser-warning':'1'}}).then(r=>r.json());
    for(; n < msgs.length; n++){ const d = document.createElement('div'); d.className = 'b '+(msgs[n].from==='me'?'me':'bot');
      d.innerHTML = render(msgs[n].text); box.appendChild(d); box.scrollTop = box.scrollHeight; } }, 800);
});
</script></body></html>"""

if __name__ == "__main__":
    app.run(port=5055, debug=False, threaded=True)
