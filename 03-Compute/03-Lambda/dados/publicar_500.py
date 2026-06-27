#!/usr/bin/env python3
"""Publica 500 pedidos na API da Fase 2 (carga para a fila SQS).

Os 500 sao deterministicos: ciclam os 10 pedidos fixos de pedidos.json
(50 vezes), com pedido_id unico PED-0001..PED-0500. Assim o numero de
objetos no S3 (500) e o faturamento por cidade (50x o dos 10) sao iguais
para todos os alunos.

Performance: cada worker mantem UMA conexao HTTPS viva (keep-alive) e dispara
varias requisicoes nela. Isso evita o handshake TLS a cada POST (que e o
gargalo: ~280ms por requisicao), saltando de ~10/s para centenas/s.

Mostra uma barra de progresso em tempo real (atualiza na mesma linha).

Uso (a variavel API vem do passo de captura do lab):
    python3 publicar_500.py "$API"
"""
import concurrent.futures
import http.client
import json
import os
import sys
import threading
import time
from urllib.parse import urlparse

if len(sys.argv) < 2:
    print("uso: python3 publicar_500.py <API_URL>")
    sys.exit(1)

HOST = urlparse(sys.argv[1]).netloc
DIR = os.path.dirname(os.path.abspath(__file__))
base = json.load(open(os.path.join(DIR, "pedidos.json"), encoding="utf-8"))

TOTAL = 500
WORKERS = 30
HEADERS = {"Content-Type": "application/json", "Connection": "keep-alive"}

# Uma conexao HTTPS por thread (reutilizada entre requisicoes).
_local = threading.local()


def _conn():
    c = getattr(_local, "conn", None)
    if c is None:
        c = _local.conn = http.client.HTTPSConnection(HOST, timeout=15)
    return c


def envia(i):
    pedido = dict(base[i % len(base)])
    pedido["pedido_id"] = f"PED-{i + 1:04d}"
    body = json.dumps(pedido, ensure_ascii=False)
    for tentativa in range(2):  # 1 retry: se a conexao keep-alive caiu, reabre
        try:
            c = _conn()
            c.request("POST", "/pedidos", body, HEADERS)
            resp = c.getresponse()
            resp.read()  # precisa drenar para reaproveitar a conexao
            return 200 <= resp.status < 300
        except Exception:
            try:
                _local.conn.close()
            except Exception:
                pass
            _local.conn = None  # forca reabrir no proximo loop
    return False


def barra(feitos, ok, total, t0):
    pct = feitos * 100 // total
    cheio = pct // 5
    barra_txt = "#" * cheio + "." * (20 - cheio)
    taxa = feitos / max(time.time() - t0, 0.001)
    sys.stdout.write(
        f"\r[{barra_txt}] {pct:3d}%  {feitos}/{total} pedidos"
        f"  (ok: {ok}, {taxa:.0f}/s)   "
    )
    sys.stdout.flush()


def main():
    t0 = time.time()
    feitos = ok = 0
    print(f"Publicando {TOTAL} pedidos em https://{HOST}/pedidos ...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futuros = [ex.submit(envia, i) for i in range(TOTAL)]
        for fut in concurrent.futures.as_completed(futuros):
            feitos += 1
            ok += 1 if fut.result() else 0
            if feitos % 10 == 0 or feitos == TOTAL:
                barra(feitos, ok, TOTAL, t0)
    print()
    dur = time.time() - t0
    print(f"Concluido: {ok}/{TOTAL} pedidos publicados em {dur:.0f}s.")
    if ok < TOTAL:
        print(f"ATENCAO: {TOTAL - ok} falharam. Rode de novo para completar os que faltaram.")


if __name__ == "__main__":
    main()
