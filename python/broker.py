import zmq
from .comum import mostrar


def iniciar():
    contexto = zmq.Context.instance()
    entrada = contexto.socket(zmq.ROUTER)
    saida = contexto.socket(zmq.DEALER)
    entrada.bind('tcp://*:5555')
    saida.bind('tcp://*:5556')
    mostrar('broker', 'INICIO', 'Clientes: 5555 | Servidores: 5556')
    try:
        zmq.proxy(entrada, saida)
    finally:
        entrada.close()
        saida.close()


if __name__ == '__main__':
    iniciar()
