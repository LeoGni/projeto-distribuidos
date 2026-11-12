from datetime import datetime, timezone
from uuid import uuid4
import msgpack


def horario():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def codigo():
    return str(uuid4())


def empacotar(dados):
    return msgpack.packb(dados, use_bin_type=True)


def desempacotar(dados):
    return msgpack.unpackb(dados, raw=False)


def mostrar(nome, acao, dados):
    print(f'[{horario()}] {nome} {acao}: {dados}', flush=True)
