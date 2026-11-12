import zmq
from .comum import mostrar


def iniciar():
    contexto = zmq.Context.instance()
    entrada = contexto.socket(zmq.XSUB)
    saida = contexto.socket(zmq.XPUB)
    entrada.bind('tcp://*:5557')
    saida.bind('tcp://*:5558')
    mostrar('pubproxy', 'INICIO', 'XSUB: 5557 | XPUB: 5558')
    try:
        zmq.proxy(entrada, saida)
    finally:
        entrada.close()
        saida.close()


if __name__ == '__main__':
    iniciar()
