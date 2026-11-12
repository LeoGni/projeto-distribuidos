import os
import re
import time
from datetime import datetime, timedelta, timezone
import zmq
from .banco import Banco
from .comum import horario, codigo, empacotar, desempacotar, mostrar

nome = os.getenv('SERVER_NAME', 'server1')
padrao_canal = re.compile(r'^[A-Za-z0-9_-]{1,32}$')


class Relogio:
    def __init__(self):
        self.logico = 0
        self.diferenca = 0.0

    def receber(self, dados):
        valor = dados.get('clock', 0) if isinstance(dados, dict) else 0
        if isinstance(valor, int) and valor >= 0:
            self.logico = max(self.logico, valor)

    def agora(self):
        return (datetime.now(timezone.utc) + timedelta(seconds=self.diferenca)).isoformat(timespec='milliseconds')

    def enviar(self, dados):
        self.logico += 1
        dados['clock'] = self.logico
        dados['sent_at'] = self.agora()
        return dados

    def sincronizar(self, hora, inicio, fim):
        instante = datetime.fromisoformat(hora).timestamp()
        self.diferenca = instante - (inicio + fim) / 2


def resposta(dados, sucesso=True, relogio=None):
    retorno = {'ok': sucesso, 'data': dados, 'sent_at': horario(), 'from': nome}
    if relogio is not None:
        relogio.enviar(retorno)
    return retorno


def atender(pedido, banco, publicador=None, relogio=None):
    if not isinstance(pedido, dict):
        return resposta({'error': 'invalid_request'}, False, relogio)

    acao = pedido.get('action')
    dados = pedido.get('data')
    if not isinstance(dados, dict):
        dados = {}

    usuario = dados.get('username')
    usuario = usuario.strip() if isinstance(usuario, str) else ''
    canal = dados.get('channel')
    enviado = pedido.get('sent_at')
    enviado = enviado if isinstance(enviado, str) and enviado else horario()

    if acao == 'login':
        if not 1 <= len(usuario) <= 64:
            return resposta({'error': 'invalid_username'}, False, relogio)
        banco.registrar(codigo(), 'login', usuario, None, enviado, horario())
        return resposta({'username': usuario, 'status': 'logged_in'}, relogio=relogio)

    if acao == 'channels':
        return resposta({'channels': banco.canais()}, relogio=relogio)

    if acao == 'create_channel':
        if not 1 <= len(usuario) <= 64:
            return resposta({'error': 'invalid_username'}, False, relogio)
        if not isinstance(canal, str) or not padrao_canal.fullmatch(canal):
            return resposta({'error': 'invalid_channel_name'}, False, relogio)
        if banco.existe(canal):
            return resposta({'error': 'channel_exists'}, False, relogio)
        banco.registrar(codigo(), 'canal', usuario, canal, enviado, horario())
        return resposta({'channel': canal, 'status': 'created'}, relogio=relogio)

    if acao == 'history':
        if canal is not None and (not isinstance(canal, str) or not banco.existe(canal)):
            return resposta({'error': 'channel_not_found'}, False, relogio)
        return resposta({'messages': banco.historico(canal)}, relogio=relogio)

    if acao == 'publish':
        mensagem = dados.get('message')
        if not 1 <= len(usuario) <= 64:
            return resposta({'error': 'invalid_username'}, False, relogio)
        if not isinstance(canal, str) or not banco.existe(canal):
            return resposta({'error': 'channel_not_found'}, False, relogio)
        if not isinstance(mensagem, str) or not 1 <= len(mensagem) <= 1000:
            return resposta({'error': 'invalid_message'}, False, relogio)
        if publicador is None:
            return resposta({'error': 'publisher_unavailable'}, False, relogio)
        publicacao = {
            'channel': canal,
            'username': usuario,
            'message': mensagem,
            'sent_at': horario(),
            'from': nome
        }
        if relogio is not None:
            relogio.enviar(publicacao)
        banco.gravar_mensagem('publicacao', publicacao, usuario, canal)
        publicador.send_multipart([canal.encode('utf-8'), empacotar(publicacao)])
        mostrar(nome, 'PUBLICOU', publicacao)
        return resposta({'status': 'published', 'channel': canal}, relogio=relogio)

    return resposta({'error': 'unknown_action'}, False, relogio)


def consultar(contexto, relogio, acao):
    conexao = contexto.socket(zmq.REQ)
    conexao.setsockopt(zmq.LINGER, 0)
    conexao.setsockopt(zmq.RCVTIMEO, 2500)
    conexao.setsockopt(zmq.SNDTIMEO, 2500)
    conexao.connect(f"tcp://{os.getenv('REFERENCE_HOST', 'referencia')}:5559")
    pedido = relogio.enviar({'action': acao, 'name': nome})
    try:
        mostrar(nome, 'ENVIOU_REFERENCIA', pedido)
        conexao.send(empacotar(pedido))
        retorno = desempacotar(conexao.recv())
        relogio.receber(retorno)
        mostrar(nome, 'RECEBEU_REFERENCIA', retorno)
        return retorno
    except (zmq.ZMQError, ValueError, TypeError) as erro:
        mostrar(nome, 'FALHA_REFERENCIA', str(erro))
        return None
    finally:
        conexao.close()


class Eleicao:
    def __init__(self, contexto, relogio, publicador, banco):
        self.contexto = contexto
        self.relogio = relogio
        self.publicador = publicador
        self.banco = banco
        self.coordenador = None
        self.rank = 0
        self.servidores = []
        self.pendente = False
        self.ultimo_aviso = 0

    def pedir(self, destino, acao, dados=None):
        conexao = self.contexto.socket(zmq.REQ)
        conexao.setsockopt(zmq.LINGER, 0)
        conexao.setsockopt(zmq.RCVTIMEO, 1700 if acao == 'sync' else 900)
        conexao.setsockopt(zmq.SNDTIMEO, 900)
        conexao.connect(f'tcp://{destino}:5560')
        try:
            pedido = self.relogio.enviar({'action': acao, 'name': nome})
            if dados:
                pedido.update(dados)
            mostrar(nome, 'ENVIOU_SERVIDOR', {'para': destino, 'pedido': pedido})
            conexao.send(empacotar(pedido))
            resposta = desempacotar(conexao.recv())
            self.relogio.receber(resposta)
            mostrar(nome, 'RECEBEU_SERVIDOR', {'de': destino, 'resposta': resposta})
            return resposta
        except (zmq.ZMQError, ValueError, TypeError) as erro:
            mostrar(nome, 'SERVIDOR_INDISPONIVEL', {'servidor': destino, 'erro': str(erro)})
            return None
        finally:
            conexao.close()

    def listar(self):
        retorno = consultar(self.contexto, self.relogio, 'list')
        if retorno and retorno.get('ok'):
            self.servidores = retorno.get('servers', [])

    def anunciar(self):
        mensagem = self.relogio.enviar({'coordinator': nome, 'rank': self.rank})
        self.publicador.send_multipart([b'servers', empacotar(mensagem)])
        mostrar(nome, 'COORDENADOR_ELEITO', mensagem)
        self.ultimo_aviso = time.monotonic()

    def eleger(self):
        self.listar()
        maiores = sorted((servidor for servidor in self.servidores if servidor['rank'] > self.rank),
                        key=lambda servidor: servidor['rank'], reverse=True)
        for servidor in maiores:
            retorno = self.pedir(servidor['name'], 'election')
            if retorno and retorno.get('ok'):
                self.coordenador = servidor['name']
                self.pendente = False
                mostrar(nome, 'AGUARDANDO_COORDENADOR', servidor['name'])
                return
        self.coordenador = nome
        self.pendente = False
        self.anunciar()

    def receber(self, pedido):
        self.relogio.receber(pedido)
        acao = pedido.get('action') if isinstance(pedido, dict) else None
        if acao == 'election':
            self.pendente = True
            dados = {'ok': True, 'status': 'OK', 'name': nome}
        elif acao == 'time':
            if self.coordenador == nome:
                self.listar()
                if any(servidor['rank'] > self.rank for servidor in self.servidores):
                    self.eleger()
            if self.coordenador == nome:
                self.berkeley()
                dados = {'ok': True, 'time': self.relogio.agora(), 'coordinator': nome}
            else:
                dados = {'ok': False, 'error': 'nao_coordenador', 'coordinator': self.coordenador}
        elif acao == 'sync':
            conhecidos = pedido.get('known', {})
            if not isinstance(conhecidos, dict):
                dados = {'ok': False, 'error': 'resumo_invalido'}
            else:
                dados = {'ok': True, 'records': self.banco.pendentes(conhecidos, 100)}
        elif acao == 'sample':
            dados = {'ok': True, 'time': self.relogio.agora()}
        else:
            dados = {'ok': False, 'error': 'acao_desconhecida'}
        return self.relogio.enviar(dados)

    def berkeley(self):
        ajustes = [0.0]
        for servidor in self.servidores:
            outro = servidor['name']
            if outro == nome:
                continue
            inicio = time.time()
            resposta = self.pedir(outro, 'sample')
            fim = time.time()
            if resposta and resposta.get('ok'):
                try:
                    instante = datetime.fromisoformat(resposta['time']).timestamp()
                    ajustes.append(instante - ((inicio + fim) / 2 + self.relogio.diferenca))
                except (ValueError, TypeError, KeyError):
                    pass
        ajuste = sum(ajustes) / len(ajustes)
        self.relogio.diferenca += ajuste
        mostrar(nome, 'BERKELEY', {'amostras': len(ajustes), 'ajuste_segundos': round(ajuste, 5)})

    def sincronizar(self):
        if self.coordenador is None:
            self.eleger()
            return
        if self.coordenador == nome:
            self.berkeley()
            return
        inicio = time.time()
        resposta = self.pedir(self.coordenador, 'time')
        fim = time.time()
        if resposta and resposta.get('ok') and resposta.get('time'):
            self.relogio.sincronizar(resposta['time'], inicio, fim)
            mostrar(nome, 'RELOGIO_SINCRONIZADO', {'coordenador': self.coordenador, 'diferenca_segundos': round(self.relogio.diferenca, 5)})
        else:
            self.coordenador = None
            self.eleger()

    def sincronizar_dados(self):
        self.listar()
        for servidor in self.servidores:
            outro = servidor['name']
            if outro == nome:
                continue
            total = 0
            for _ in range(4):
                retorno = self.pedir(outro, 'sync', {'known': self.banco.resumo()})
                if not retorno or not retorno.get('ok'):
                    break
                registros = retorno.get('records', [])
                if not isinstance(registros, list):
                    break
                if registros:
                    total += self.banco.receber(registros)
                if len(registros) < 100:
                    break
            if total:
                mostrar(nome, 'REPLICOU', {'de': outro, 'novos': total, 'total': self.banco.resumo()})

    def receber_anuncio(self, mensagem):
        try:
            dados = desempacotar(mensagem)
            self.relogio.receber(dados)
            candidato = dados.get('coordinator')
            rank = dados.get('rank', 0)
            if isinstance(candidato, str) and isinstance(rank, int) and rank >= self.rank:
                self.coordenador = candidato
                mostrar(nome, 'NOVO_COORDENADOR', dados)
        except (ValueError, TypeError, AttributeError) as erro:
            mostrar(nome, 'ERRO_ANUNCIO', str(erro))

def iniciar():
    contexto = zmq.Context.instance()
    conexao = contexto.socket(zmq.REP)
    conexao.connect(f"tcp://{os.getenv('BROKER_HOST', 'broker')}:5556")
    publicador = contexto.socket(zmq.PUB)
    publicador.connect(f"tcp://{os.getenv('PUBPROXY_HOST', 'pubproxy')}:5557")
    escuta = contexto.socket(zmq.REP)
    escuta.bind(f"tcp://{os.getenv('SERVER_BIND_HOST', '*')}:5560")
    assinante = contexto.socket(zmq.SUB)
    assinante.connect(f"tcp://{os.getenv('PUBPROXY_HOST', 'pubproxy')}:5558")
    assinante.setsockopt(zmq.SUBSCRIBE, b'servers')
    banco = Banco(os.getenv('DB_PATH', '/data/events.sqlite3'), nome)
    relogio = Relogio()
    eleicao = Eleicao(contexto, relogio, publicador, banco)
    mostrar(nome, 'INICIO', 'Servidor pronto')
    time.sleep(1)
    cadastro = consultar(contexto, relogio, 'rank')
    if cadastro and cadastro.get('ok'):
        eleicao.rank = cadastro['rank']
    consultar(contexto, relogio, 'heartbeat')
    eleicao.eleger()
    quantidade = 0
    ultimo_heartbeat = time.monotonic()
    ultima_verificacao = time.monotonic()
    ultimo_relogio = time.monotonic()
    ultima_replica = 0
    monitor = zmq.Poller()
    monitor.register(conexao, zmq.POLLIN)
    monitor.register(escuta, zmq.POLLIN)
    monitor.register(assinante, zmq.POLLIN)
    try:
        while True:
            eventos = dict(monitor.poll(500))
            if assinante in eventos:
                topico, mensagem = assinante.recv_multipart()
                if topico == b'servers':
                    eleicao.receber_anuncio(mensagem)
            if escuta in eventos:
                try:
                    pedido = desempacotar(escuta.recv())
                    mostrar(nome, 'RECEBEU_SERVIDOR', pedido)
                    retorno = eleicao.receber(pedido)
                except Exception as erro:
                    mostrar(nome, 'ERRO_SERVIDOR', str(erro))
                    retorno = relogio.enviar({'ok': False, 'error': 'pedido_invalido'})
                escuta.send(empacotar(retorno))
            if conexao in eventos:
                try:
                    pedido = desempacotar(conexao.recv())
                    relogio.receber(pedido)
                    mostrar(nome, 'RECEBEU', pedido)
                    banco.gravar_mensagem('pedido', pedido)
                    retorno = atender(pedido, banco, publicador, relogio)
                except Exception as erro:
                    mostrar(nome, 'ERRO', str(erro))
                    retorno = resposta({'error': 'invalid_request'}, False, relogio)
                banco.gravar_mensagem('resposta', retorno)
                mostrar(nome, 'ENVIOU', retorno)
                conexao.send(empacotar(retorno))
                quantidade += 1
                if quantidade % 10 == 0:
                    retorno = consultar(contexto, relogio, 'heartbeat')
                    if retorno and retorno.get('error') == 'servidor_nao_cadastrado':
                        cadastro = consultar(contexto, relogio, 'rank')
                        if cadastro and cadastro.get('ok'):
                            eleicao.rank = cadastro['rank']
                            eleicao.pendente = True
                    eleicao.listar()
                    ultimo_heartbeat = time.monotonic()
                if quantidade % 15 == 0:
                    eleicao.sincronizar()
                    ultimo_relogio = time.monotonic()
            agora = time.monotonic()
            if agora - ultima_replica >= 3:
                eleicao.sincronizar_dados()
                ultima_replica = time.monotonic()
            if agora - ultimo_heartbeat >= 15:
                retorno = consultar(contexto, relogio, 'heartbeat')
                if retorno and retorno.get('error') == 'servidor_nao_cadastrado':
                    cadastro = consultar(contexto, relogio, 'rank')
                    if cadastro and cadastro.get('ok'):
                        eleicao.rank = cadastro['rank']
                        eleicao.pendente = True
                ultimo_heartbeat = agora
            if eleicao.pendente:
                eleicao.eleger()
            if agora - ultima_verificacao >= 6:
                eleicao.listar()
                if eleicao.coordenador is None:
                    eleicao.eleger()
                elif eleicao.coordenador == nome and any(servidor['rank'] > eleicao.rank for servidor in eleicao.servidores):
                    eleicao.eleger()
                elif eleicao.coordenador != nome:
                    if not eleicao.pedir(eleicao.coordenador, 'sample'):
                        eleicao.coordenador = None
                        eleicao.eleger()
                elif agora - eleicao.ultimo_aviso >= 10:
                    eleicao.anunciar()
                ultima_verificacao = time.monotonic()
            if agora - ultimo_relogio >= 30:
                eleicao.sincronizar()
                ultimo_relogio = time.monotonic()
    finally:
        conexao.close()
        publicador.close()
        escuta.close()
        assinante.close()


if __name__ == '__main__':
    iniciar()
