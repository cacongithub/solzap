"""Cliente JSON-RPC mínimo da Solana (só o que o kit usa)."""
import itertools

import requests


class RPCError(Exception):
    pass


class RPC:
    def __init__(self, url, timeout=20):
        self.url = url
        self.timeout = timeout
        self._ids = itertools.count(1)

    def call(self, method, *params):
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": list(params)}
        resp = requests.post(self.url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RPCError(f"{method}: {data['error']}")
        return data["result"]

    def get_signatures_for_address(self, address, limit=10, commitment="confirmed"):
        return self.call("getSignaturesForAddress", str(address), {"limit": limit, "commitment": commitment})

    def get_transaction(self, signature, commitment="confirmed"):
        return self.call(
            "getTransaction",
            str(signature),
            {"encoding": "jsonParsed", "commitment": commitment, "maxSupportedTransactionVersion": 0},
        )

    def get_latest_blockhash(self, commitment="confirmed"):
        return self.call("getLatestBlockhash", {"commitment": commitment})["value"]["blockhash"]

    def get_balance(self, address):
        return self.call("getBalance", str(address))["value"]

    def get_account_info(self, address):
        return self.call("getAccountInfo", str(address), {"encoding": "jsonParsed"})["value"]

    def get_token_balance(self, token_account):
        """Saldo bruto (inteiro) de uma conta de token; 0 se ela não existe."""
        try:
            return int(self.call("getTokenAccountBalance", str(token_account))["value"]["amount"])
        except RPCError:
            return 0

    def send_transaction(self, raw_b64):
        return self.call("sendTransaction", raw_b64, {"encoding": "base64", "preflightCommitment": "confirmed"})

    def get_signature_status(self, signature):
        res = self.call("getSignatureStatuses", [str(signature)], {"searchTransactionHistory": True})
        return res["value"][0]
