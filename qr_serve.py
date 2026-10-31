#!/usr/bin/env python3
"""qr-serve — abre o teu site no telemóvel em 2 segundos.

Dois modos:
  qr-serve [pasta]        serve uma pasta estática, com live reload
  qr-serve -f 3000        encaminha um dev server (Next, Vite...) que só escuta em localhost

Mostra o endereço da rede local e um QR code no terminal.
"""
import argparse
import asyncio
import http.server
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from functools import partial
from pathlib import Path

IGNORAR = {"node_modules", ".git", ".next", ".turbo", ".venv", "__pycache__"}

SCRIPT_RELOAD = (
    b"<script>(function(){var v=null;function t(){fetch('/__qr_reload',{cache:'no-store'})"
    b".then(function(r){return r.text()}).then(function(x){if(v===null){v=x}else if(v!==x){"
    b"location.reload()}}).catch(function(){})}setInterval(t,1000);t()})();</script>"
)

# ---------- apresentação ----------


def _cor(cod, txt):
    return f"\033[{cod}m{txt}\033[0m" if sys.stdout.isatty() else txt


def verde(t): return _cor("32", t)
def amarelo(t): return _cor("33", t)
def vermelho(t): return _cor("31", t)
def cinza(t): return _cor("90", t)
def negrito(t): return _cor("1", t)


def preparar_consola():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if os.name == "nt":
        os.system("")  # activa cores ANSI no terminal do Windows


# ---------- rede ----------


def _prioridade(ip):
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("10."):
        return 1
    if re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip):
        return 2
    return 3


def ips_lan():
    """IPs da máquina na rede local. O primeiro é o da rota por defeito (o mais provável)."""
    candidatos = []
    for alvo in ("8.8.8.8", "10.255.255.255"):  # não envia nada, só descobre a rota
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((alvo, 80))
            candidatos.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
    principal = candidatos[0] if candidatos else None
    outros = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            outros.append(info[4][0])
    except OSError:
        pass
    res = []
    for ip in ([principal] if principal else []) + sorted(set(candidatos + outros), key=_prioridade):
        if ip and not ip.startswith(("127.", "169.254.")) and ip not in res:
            res.append(ip)
    return res


def porta_livre(inicio):
    for p in range(inicio, inicio + 20):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise SystemExit(vermelho(f"Nenhuma porta livre entre {inicio} e {inicio + 19}."))


def algo_a_escutar(porta):
    for host, familia in (("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)):
        try:
            s = socket.socket(familia, socket.SOCK_STREAM)
            s.settimeout(0.5)
            ok = s.connect_ex((host, porta)) == 0
            s.close()
            if ok:
                return True
        except OSError:
            pass
    return False


def mostrar_qr(url):
    try:
        import segno
        segno.make(url, error="m").terminal(out=sys.stdout, compact=True, border=2)
    except Exception as e:  # noqa: BLE001
        print(amarelo(f"(não consegui desenhar o QR aqui: {type(e).__name__})"))


def banner(titulo, porta, ips, ip_escolhido):
    print()
    print(negrito(f"  qr-serve — {titulo}"))
    print(f"  Local:  http://localhost:{porta}")
    if ip_escolhido:
        url = f"http://{ip_escolhido}:{porta}"
        print(f"  Rede:   {negrito(url)}   {cinza('<- telemóvel')}")
        outros = [i for i in ips if i != ip_escolhido]
        if outros:
            print(cinza("  Outros IPs: " + ", ".join(f"http://{i}:{porta}" for i in outros[:3])))
            print(cinza("  (se o QR não abrir, tenta outro com --ip)"))
        print()
        mostrar_qr(url)
    else:
        url = None
        print(amarelo("  Não encontrei IP da rede local. Estás ligado ao Wi-Fi?"))
    print()
    if os.name == "nt":
        print(cinza("  Windows: se o telemóvel não abrir, permite o Python na firewall (rede privada)."))
    print(cinza("  Telemóvel e PC têm de estar no mesmo Wi-Fi.  Ctrl+C para parar.\n"))


# ---------- modo pasta estática ----------

_cache_versao = {"t": 0.0, "v": ""}


def versao_da_pasta(raiz):
    """Muda sempre que um ficheiro é criado, alterado ou apagado."""
    agora = time.time()
    if agora - _cache_versao["t"] < 0.7:
        return _cache_versao["v"]
    maior, n = 0, 0
    for d, dirs, ficheiros in os.walk(raiz):
        dirs[:] = [x for x in dirs if x not in IGNORAR]
        for f in ficheiros:
            try:
                maior = max(maior, os.stat(os.path.join(d, f)).st_mtime_ns)
                n += 1
            except OSError:
                pass
    _cache_versao.update(t=agora, v=f"{maior}-{n}")
    return _cache_versao["v"]


class Handler(http.server.SimpleHTTPRequestHandler):
    spa = False
    reload = True

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass

    def log_request(self, code="-", size="-"):
        if self.path.startswith("/__qr_reload"):
            return
        c = str(code)
        cor = verde if c.startswith(("2", "3")) else vermelho if c.startswith(("4", "5")) else cinza
        print(f"  {cinza(time.strftime('%H:%M:%S'))} {self.command:<4} {self.path[:70]}  {cor(c)}")

    def _alvo(self, caminho):
        fs = Path(self.translate_path(caminho))
        if fs.is_dir():
            if not caminho.endswith("/"):
                return None  # deixa o servidor fazer o redirect para a barra final
            for nome in ("index.html", "index.htm"):
                if (fs / nome).is_file():
                    return fs / nome
            return None
        return fs if fs.is_file() else None

    def _servir_html(self, ficheiro):
        try:
            dados = ficheiro.read_bytes()
        except OSError:
            self.send_error(404)
            return
        if self.reload:
            i = dados.lower().rfind(b"</body>")
            dados = dados[:i] + SCRIPT_RELOAD + dados[i:] if i >= 0 else dados + SCRIPT_RELOAD
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        caminho = self.path.split("?", 1)[0].split("#", 1)[0]
        if caminho == "/__qr_reload":
            corpo = versao_da_pasta(self.directory).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        alvo = self._alvo(caminho)
        if alvo is not None and alvo.suffix.lower() in (".html", ".htm"):
            return self._servir_html(alvo)
        if alvo is None and self.spa and "." not in Path(caminho).name:
            idx = Path(self.directory) / "index.html"
            if idx.is_file():
                return self._servir_html(idx)
        return super().do_GET()


class Servidor(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return  # o telemóvel fechou a ligação a meio: normal
        super().handle_error(request, client_address)


def modo_pasta(args):
    raiz = Path(args.pasta).expanduser().resolve()
    if not raiz.is_dir():
        print(vermelho(f"Pasta não existe: {raiz}"))
        return 1
    Handler.spa = args.spa
    Handler.reload = not args.sem_reload

    porta = porta_livre(args.porta)
    if porta != args.porta:
        print(amarelo(f"Porta {args.porta} ocupada, a usar {porta}."))
    servidor = Servidor(("0.0.0.0", porta), partial(Handler, directory=str(raiz)))

    ips = ips_lan()
    ip = args.ip or (ips[0] if ips else None)
    banner(f"a servir {raiz}", porta, ips, ip)
    if not (raiz / "index.html").is_file():
        if (raiz / "package.json").is_file():
            print(amarelo("  Isto parece um projecto com dev server. Corre-o e usa:  qr-serve -f 3000\n"))
        else:
            print(amarelo("  Não há index.html nesta pasta: vais ver a listagem de ficheiros.\n"))
    if not args.sem_reload:
        print(cinza("  Live reload activo: a página recarrega quando gravas um ficheiro.\n"))
    if args.abrir:
        threading.Timer(0.5, lambda: webbrowser.open(f"http://localhost:{porta}")).start()
    try:
        servidor.serve_forever()
    finally:
        servidor.server_close()
    return 0


# ---------- modo encaminhar (dev server só em localhost) ----------


async def _relay(leitor, escritor):
    try:
        while True:
            dados = await leitor.read(65536)
            if not dados:
                break
            escritor.write(dados)
            await escritor.drain()
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            escritor.close()
        except Exception:  # noqa: BLE001
            pass


async def _ligar(cliente_r, cliente_w, alvo):
    sr = sw = None
    for host in ("127.0.0.1", "::1"):  # no Windows o 'localhost' costuma ser IPv6
        try:
            sr, sw = await asyncio.open_connection(host, alvo)
            break
        except OSError:
            continue
    if sw is None:
        print(vermelho(f"  Ligação recusada: nada a escutar na porta {alvo}."))
        cliente_w.close()
        return
    await asyncio.gather(_relay(cliente_r, sw), _relay(sr, cliente_w))


async def _correr_encaminhamento(porta, alvo):
    srv = await asyncio.start_server(lambda r, w: _ligar(r, w, alvo), "0.0.0.0", porta)
    async with srv:
        await srv.serve_forever()


def modo_encaminhar(args):
    alvo = args.encaminhar
    if not algo_a_escutar(alvo):
        print(amarelo(f"Não encontrei nada a correr na porta {alvo}. Arranca primeiro o dev server."))
    porta = porta_livre(args.porta)
    if porta == alvo:
        porta = porta_livre(alvo + 1)
    if porta != args.porta:
        print(amarelo(f"Porta {args.porta} ocupada, a usar {porta}."))
    ips = ips_lan()
    ip = args.ip or (ips[0] if ips else None)
    banner(f"a encaminhar localhost:{alvo}", porta, ips, ip)
    print(cinza("  Se aparecer 'Invalid Host header' ou o HMR falhar: Vite -> server.allowedHosts,"))
    print(cinza("  Next -> allowedDevOrigins (adiciona o IP da rede).\n"))
    if args.abrir:
        threading.Timer(0.5, lambda: webbrowser.open(f"http://localhost:{porta}")).start()
    asyncio.run(_correr_encaminhamento(porta, alvo))
    return 0


# ---------- entrada ----------


def main():
    preparar_consola()
    ap = argparse.ArgumentParser(
        prog="qr-serve",
        description="Serve uma pasta (ou encaminha um dev server) na rede local e mostra um QR code.")
    ap.add_argument("pasta", nargs="?", default=".", help="pasta a servir (padrão: actual)")
    ap.add_argument("-p", "--porta", type=int, default=8000, help="porta (padrão: 8000)")
    ap.add_argument("-f", "--encaminhar", type=int, metavar="PORTA",
                    help="encaminha o dev server que corre em localhost:PORTA")
    ap.add_argument("--ip", help="força o IP usado no QR (se houver várias redes)")
    ap.add_argument("--spa", action="store_true", help="rotas desconhecidas devolvem o index.html")
    ap.add_argument("--sem-reload", action="store_true", help="desliga o live reload")
    ap.add_argument("--abrir", action="store_true", help="abre também no navegador do PC")
    args = ap.parse_args()
    if args.encaminhar:
        return modo_encaminhar(args)
    return modo_pasta(args)


def _entrada():
    try:
        return main()
    except KeyboardInterrupt:
        print("\nParado.")
        return 0


if __name__ == "__main__":
    sys.exit(_entrada())