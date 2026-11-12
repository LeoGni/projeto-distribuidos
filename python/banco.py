import sqlite3
import msgpack
from .comum import codigo, horario


class Banco:
    def __init__(self, caminho, nome='server1'):
        self.nome = nome
        self.conexao = sqlite3.connect(caminho, timeout=20)
        self.conexao.execute('PRAGMA journal_mode=WAL')
        self.conexao.execute('PRAGMA busy_timeout=20000')
        with self.conexao:
            self.conexao.execute('''CREATE TABLE IF NOT EXISTS eventos (
                id TEXT PRIMARY KEY,
                tipo TEXT NOT NULL,
                usuario TEXT NOT NULL,
                canal TEXT,
                enviado_em TEXT NOT NULL,
                recebido_em TEXT NOT NULL
            )''')
            self.conexao.execute('''CREATE TABLE IF NOT EXISTS mensagens (
                id TEXT PRIMARY KEY,
                tipo TEXT NOT NULL,
                usuario TEXT,
                canal TEXT,
                conteudo BLOB NOT NULL,
                registrado_em TEXT NOT NULL
            )''')
            self.conexao.execute('''CREATE TABLE IF NOT EXISTS registros (
                id TEXT PRIMARY KEY,
                origem TEXT NOT NULL,
                sequencia INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                conteudo BLOB NOT NULL,
                criado_em TEXT NOT NULL,
                UNIQUE (origem, sequencia)
            )''')
            self.conexao.execute('''CREATE TABLE IF NOT EXISTS controle (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            )''')
            antigo = self.conexao.execute("SELECT valor FROM controle WHERE chave = 'migrado'").fetchone()
            if antigo is None:
                linhas = []
                for linha in self.conexao.execute('SELECT id, tipo, usuario, canal, enviado_em, recebido_em FROM eventos'):
                    identificador, tipo, usuario, canal, enviado, recebido = linha
                    linhas.append((recebido, identificador, 'evento', {
                        'id': identificador, 'tipo': tipo, 'usuario': usuario, 'canal': canal,
                        'enviado_em': enviado, 'recebido_em': recebido
                    }))
                for linha in self.conexao.execute('SELECT id, tipo, usuario, canal, conteudo, registrado_em FROM mensagens'):
                    identificador, tipo, usuario, canal, conteudo, registrado = linha
                    linhas.append((registrado, identificador, 'mensagem', {
                        'id': identificador, 'tipo': tipo, 'usuario': usuario, 'canal': canal,
                        'conteudo': conteudo, 'registrado_em': registrado
                    }))
                linhas.sort(key=lambda linha: (linha[0], linha[1]))
                proxima = self.conexao.execute(
                    'SELECT COALESCE(MAX(sequencia), 0) FROM registros WHERE origem = ?', (self.nome,)
                ).fetchone()[0]
                for criado, identificador, tipo, dados in linhas:
                    presente = self.conexao.execute('SELECT 1 FROM registros WHERE id = ?', (identificador,)).fetchone()
                    if presente:
                        continue
                    proxima += 1
                    self.conexao.execute(
                        'INSERT INTO registros VALUES (?, ?, ?, ?, ?, ?)',
                        (identificador, self.nome, proxima, tipo, msgpack.packb(dados, use_bin_type=True), criado)
                    )
                self.conexao.execute("INSERT INTO controle VALUES ('migrado', 'sim')")
        self.sequencia = self.conexao.execute(
            'SELECT COALESCE(MAX(sequencia), 0) FROM registros WHERE origem = ?', (self.nome,)
        ).fetchone()[0]

    def salvar(self, tipo, dados):
        self.sequencia += 1
        registro = {
            'id': dados['id'], 'origem': self.nome, 'sequencia': self.sequencia,
            'tipo': tipo, 'conteudo': msgpack.packb(dados, use_bin_type=True), 'criado_em': horario()
        }
        with self.conexao:
            self._inserir(registro)
        return registro

    def _inserir(self, registro):
        existe = self.conexao.execute('SELECT 1 FROM registros WHERE id = ?', (registro['id'],)).fetchone()
        if existe:
            return False
        self.conexao.execute(
            'INSERT INTO registros (id, origem, sequencia, tipo, conteudo, criado_em) VALUES (?, ?, ?, ?, ?, ?)',
            (registro['id'], registro['origem'], registro['sequencia'], registro['tipo'],
             registro['conteudo'], registro['criado_em'])
        )
        dados = msgpack.unpackb(registro['conteudo'], raw=False)
        if registro['tipo'] == 'evento':
            self.conexao.execute(
                'INSERT OR IGNORE INTO eventos VALUES (?, ?, ?, ?, ?, ?)',
                (dados['id'], dados['tipo'], dados['usuario'], dados['canal'],
                 dados['enviado_em'], dados['recebido_em'])
            )
        elif registro['tipo'] == 'mensagem':
            self.conexao.execute(
                'INSERT OR IGNORE INTO mensagens VALUES (?, ?, ?, ?, ?, ?)',
                (dados['id'], dados['tipo'], dados['usuario'], dados['canal'],
                 dados['conteudo'], dados['registrado_em'])
            )
        return True

    def registrar(self, identificador, tipo, usuario, canal, enviado, recebido):
        return self.salvar('evento', {
            'id': identificador, 'tipo': tipo, 'usuario': usuario, 'canal': canal,
            'enviado_em': enviado, 'recebido_em': recebido
        })

    def gravar_mensagem(self, tipo, dados, usuario=None, canal=None):
        return self.salvar('mensagem', {
            'id': codigo(), 'tipo': tipo, 'usuario': usuario, 'canal': canal,
            'conteudo': msgpack.packb(dados, use_bin_type=True), 'registrado_em': horario()
        })

    def canais(self):
        linhas = self.conexao.execute(
            "SELECT DISTINCT canal FROM eventos WHERE tipo = 'canal' ORDER BY canal"
        ).fetchall()
        return [linha[0] for linha in linhas]

    def existe(self, canal):
        return self.conexao.execute(
            "SELECT 1 FROM eventos WHERE tipo = 'canal' AND canal = ? LIMIT 1", (canal,)
        ).fetchone() is not None

    def resumo(self):
        linhas = self.conexao.execute(
            'SELECT origem, MAX(sequencia) FROM registros GROUP BY origem'
        ).fetchall()
        return {origem: numero for origem, numero in linhas}

    def pendentes(self, conhecidos, limite=100):
        registros = []
        origens = [linha[0] for linha in self.conexao.execute('SELECT DISTINCT origem FROM registros ORDER BY origem')]
        for origem in origens:
            ultimo = conhecidos.get(origem, 0)
            if not isinstance(ultimo, int) or ultimo < 0:
                ultimo = 0
            linhas = self.conexao.execute(
                'SELECT id, origem, sequencia, tipo, conteudo, criado_em FROM registros '
                'WHERE origem = ? AND sequencia > ? ORDER BY sequencia LIMIT ?',
                (origem, ultimo, limite - len(registros))
            ).fetchall()
            for linha in linhas:
                registros.append(dict(zip(('id', 'origem', 'sequencia', 'tipo', 'conteudo', 'criado_em'), linha)))
            if len(registros) >= limite:
                break
        return registros

    def receber(self, registros):
        quantidade = 0
        with self.conexao:
            for registro in registros:
                if self._inserir(registro):
                    quantidade += 1
        return quantidade

    def historico(self, canal=None, limite=100):
        if canal is None:
            linhas = self.conexao.execute(
                "SELECT conteudo FROM mensagens WHERE tipo = 'publicacao' ORDER BY registrado_em DESC, id DESC LIMIT ?",
                (limite,)
            ).fetchall()
        else:
            linhas = self.conexao.execute(
                "SELECT conteudo FROM mensagens WHERE tipo = 'publicacao' AND canal = ? "
                'ORDER BY registrado_em DESC, id DESC LIMIT ?', (canal, limite)
            ).fetchall()
        return [msgpack.unpackb(linha[0], raw=False) for linha in reversed(linhas)]
