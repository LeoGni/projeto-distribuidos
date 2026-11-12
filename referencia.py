import os
import time
import zmq
from .comum import horario, empacotar, desempacotar, mostrar


class Referencia:
    def __init__(self, limite=45):
        self.servidores = {}
        self.proximo_rank = 1
        self.relogio = 0
        self.limite = limite

    def limpar(self):
        agora = time.monotonic()
        for nome in list(self.servidores):
            if agora - self.servidores[nome]['ultimo'] > self.limite:
                mostrar('referencia', 'INATIVO', nome)
                del self.servidores[nome]

    def atender(self, pedido):
        if not isinstance(pedido, dict):
            return {'ok': False, 'error': 'pedido_invalido'}
        self.relogio = max(self.relogio, int(pedido.get('clock', 0)))
        self.limpar()
        acao = pedido.get('action')
        nome = pedido.get('name')
        if acao == 'rank':
            if not isinstance(nome, str) or not nome:
                retorno = {'ok': False, 'error': 'nome_invalido'}
            else:
                if nome not in self.servidores:
                    self.servidores[nome] = {'rank': self.proximo_rank, 'ultimo': time.monotonic()}
                    self.proximo_rank += 1
                else:
                    self.servidores[nome]['ultimo'] = time.monotonic()
                retorno = {'ok': True, 'rank': self.servidores[nome]['rank']}
        elif acao == 'list':
            retorno = {'ok': True, 'servers': [
                {'name': n, 'rank': dados['rank']} for n, dados in sorted(
                    self.servidores.items(), key=lambda item: item[1]['rank'])
            ]}
        elif acao == 'heartbeat':
            if nome not in self.servidores:
                retorno = {'ok': False, 'error': 'servidor_nao_cadastrado'}
            else:
                self.servidores[nome]['ultimo'] = time.monotonic()
                retorno = {'ok': True, 'status': 'ativo'}
        else:
            retorno = {'ok': False, 'error': 'acao_desconhecida'}
        self.relogio += 1
        retorno['clock'] = self.relogio
        retorno['sent_at'] = horario()
        return retorno


def iniciar():
    contexto = zmq.Context.instance()
    conexao = contexto.socket(zmq.REP)
    conexao.bind('tcp://*:5559')
    referencia = Referencia(int(os.getenv('HEARTBEAT_TIMEOUT', '45')))
    mostrar('referencia', 'INICIO', 'Porta 5559')
    try:
        while True:
            if conexao.poll(1000) == 0:
                referencia.limpar()
                continue
            try:
                pedido = desempacotar(conexao.recv())
                mostrar('referencia', 'RECEBEU', pedido)
                retorno = referencia.atender(pedido)
            except Exception as erro:
                mostrar('referencia', 'ERRO', str(erro))
                referencia.relogio += 1
                retorno = {'ok': False, 'error': 'pedido_invalido', 'clock': referencia.relogio, 'sent_at': horario()}
            mostrar('referencia', 'ENVIOU', retorno)
            conexao.send(empacotar(retorno))
    finally:
        conexao.close()


if __name__ == '__main__':
    iniciar()
