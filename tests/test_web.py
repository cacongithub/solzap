from flask import Flask
from solders.keypair import Keypair

from solzap.payments import create_payment_request
from solzap.store import Store
from solzap.web import make_blueprint

MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"


def test_pay_page_behind_https_proxy_has_no_http_links(tmp_path):
    store = Store(str(tmp_path / "w.db"))
    pid = store.add_payment("5511911112222", "5511933334444",
                            create_payment_request(str(Keypair().pubkey()), "5", MINT))
    app = Flask(__name__)
    app.register_blueprint(make_blueprint(store, rpc=None, net={"name": "devnet"}))
    html = app.test_client().get(f"/pay/{pid}", headers={"X-Forwarded-Proto": "https"},
                                 base_url="http://demo.example").get_data(as_text=True)
    assert "http://demo.example" not in html and "http%3A%2F%2Fdemo.example" not in html
    assert f'data-tx-url="/api/solzap/tx/{pid}"' in html  # a página chama por caminho relativo
    assert "https%3A%2F%2Fdemo.example%2Fpay%2F" in html  # link da Phantom em https
    assert "<script>" not in html  # nada inline (CSP restrita)
