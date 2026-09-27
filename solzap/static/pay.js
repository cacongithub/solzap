// Página de pagamento do SolZap. Arquivo externo (sem script inline) para funcionar
// em sites com Content-Security-Policy restrita. Configuração vem dos data-* de #solzap.
(function () {
  const root = document.getElementById('solzap');
  const cfg = root.dataset;
  const provider = window.phantom?.solana || window.solflare || window.solana;
  const $ = (id) => document.getElementById(id);
  const headers = { 'Content-Type': 'application/json', 'ngrok-skip-browser-warning': '1' };

  function show(text, cls, link) {
    const m = $('msg');
    m.hidden = false;
    m.textContent = '';
    const span = document.createElement('span');
    if (cls) span.className = cls;
    span.textContent = text;
    m.appendChild(span);
    if (link) {
      const a = document.createElement('a');
      a.className = 'link';
      a.href = link;
      a.textContent = ' Ver na blockchain';
      m.appendChild(a);
    }
  }

  async function poll() {
    const r = await fetch(cfg.statusUrl, { headers }).then((r) => r.json()).catch(() => null);
    if (r && r.status === 'paid') { $('pending').hidden = true; show('✅ Pagamento confirmado.', 'ok', r.explorer); return; }
    if (r && r.status === 'expired') { $('pending').hidden = true; show('Esta cobrança expirou. Peça um novo link no WhatsApp.', 'err'); return; }
    setTimeout(poll, 2500);
  }

  function toBase64(bytes) {
    let s = '';
    for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s);
  }

  async function pay() {
    const btn = $('pay');
    btn.disabled = true;
    try {
      show('Conectando à carteira…');
      const { publicKey } = await provider.connect();
      show('Montando a transação…');
      const res = await fetch(cfg.txUrl, { method: 'POST', headers, body: JSON.stringify({ account: publicKey.toString() }) });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || 'erro ao montar a transação');
      const bytes = Uint8Array.from(atob(body.transaction), (c) => c.charCodeAt(0));
      const tx = solanaWeb3.Transaction.from(bytes);
      show('Assinando…');
      if (provider.signTransaction) {
        // A carteira só assina; nosso servidor envia (não depende da RPC da carteira).
        const signed = await provider.signTransaction(tx);
        show('Enviando…');
        const sub = await fetch(cfg.submitUrl, { method: 'POST', headers, body: JSON.stringify({ transaction: toBase64(signed.serialize()) }) });
        const sb = await sub.json();
        if (!sub.ok) throw new Error(sb.error || 'erro ao enviar');
      } else {
        await provider.signAndSendTransaction(tx);
      }
      show('Enviado. Aguardando confirmação na blockchain…');
    } catch (e) {
      show('Não foi possível pagar: ' + (e && e.message ? e.message : e), 'err');
      btn.disabled = false;
    }
  }

  if (cfg.status === 'pending') {
    if (provider) {
      $('open').hidden = true;
      $('pay').hidden = false;
      $('pay').addEventListener('click', pay);
    }
    poll();
  }
})();
