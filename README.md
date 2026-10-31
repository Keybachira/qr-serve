# qr-serve

Abre o teu site no telemóvel em 2 segundos. Mostra o endereço da rede local e um QR code no terminal: apontas a câmara e abre.

## Instalar (fica no PATH)

```bash
cd qr-serve
uv tool install --editable .
```

O ficheiro principal tem de se chamar `qr_serve.py` (com underscore), senão o comando não encontra o módulo. Abre um terminal novo depois de instalar.

## Usar

```bash
qr-serve                 # serve a pasta actual
qr-serve ./dist          # serve outra pasta
qr-serve -f 3000         # encaminha o dev server que corre em localhost:3000
qr-serve --spa           # rotas desconhecidas devolvem o index.html (apps React/Vue em build)
qr-serve -p 9000         # outra porta (padrão: 8000)
qr-serve --abrir         # abre também no navegador do PC
```

## Dois modos

**Pasta estática** (sites HTML, builds, `dist/`): serve os ficheiros com live reload. Quando gravas um ficheiro, a página no telemóvel recarrega sozinha. Os HTML não ficam em cache, por isso nunca vês versões antigas. Desliga o reload com `--sem-reload`.

**Encaminhar dev server** (`-f`): Next, Vite e semelhantes normalmente só escutam em `localhost`, e o telemóvel não os alcança. Com `qr-serve -f 3000`, ele abre uma porta visível na rede e reencaminha tudo para o teu dev server, incluindo WebSockets (o HMR continua a funcionar). Arranca primeiro o dev server, depois o `qr-serve`.

## Se o telemóvel não abrir

1. **Mesmo Wi-Fi**: telemóvel e PC têm de estar na mesma rede. Redes públicas e de hotéis costumam isolar os dispositivos entre si; nesse caso usa o hotspot do telemóvel e liga o PC a ele.
2. **Firewall do Windows**: na primeira vez, aparece um pedido para permitir o Python. Aceita para **redes privadas**. Se o fechaste sem querer, vai a Definições do Windows → Firewall → Permitir uma aplicação, e activa o Python.
3. **IP errado**: com VPN, WSL, VirtualBox ou Docker, o PC tem vários IPs. O primeiro é o da rota principal, e os outros aparecem listados. Força um com `--ip 192.168.1.23`.
4. **"Invalid Host header" ou o HMR falha** (só no modo `-f`): alguns dev servers rejeitam hosts desconhecidos. No Vite, adiciona o IP em `server.allowedHosts`. No Next, em `allowedDevOrigins`.

## Notas

- Só usa a biblioteca padrão, mais o `segno` para desenhar o QR (instala-se sozinho).
- Expõe a pasta a toda a rede local enquanto estiver a correr. Não o uses em Wi-Fi público com ficheiros sensíveis na pasta (um `.env`, por exemplo).
- Se o QR sair deformado, usa o Windows Terminal em vez do `cmd` clássico.