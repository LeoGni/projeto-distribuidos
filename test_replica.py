import tempfile
import sqlite3
import unittest
from pathlib import Path
from python.banco import Banco
from python.comum import horario


class TesteReplica(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.caminho = Path(self.pasta.name)
        self.um = Banco(str(self.caminho / 'um.sqlite3'), 'server1')
        self.dois = Banco(str(self.caminho / 'dois.sqlite3'), 'server2')

    def tearDown(self):
        self.um.conexao.close()
        self.dois.conexao.close()
        self.pasta.cleanup()

    def trocar(self, origem, destino):
        total = 0
        while True:
            registros = origem.pendentes(destino.resumo(), limite=2)
            total += destino.receber(registros)
            if len(registros) < 2:
                return total

    def test_replicar_eventos_e_mensagens(self):
        self.um.registrar('login1', 'login', 'ana', None, horario(), horario())
        self.um.registrar('canal1', 'canal', 'ana', 'geral', horario(), horario())
        self.um.gravar_mensagem('publicacao', {'message': 'oi', 'sent_at': horario()}, 'ana', 'geral')
        self.assertEqual(self.trocar(self.um, self.dois), 3)
        self.assertEqual(self.dois.canais(), ['geral'])
        self.assertEqual(self.dois.historico('geral')[0]['message'], 'oi')
        self.assertEqual(self.trocar(self.um, self.dois), 0)

    def test_recuperacao_apos_parada(self):
        self.um.registrar('canal2', 'canal', 'ana', 'avisos', horario(), horario())
        self.trocar(self.um, self.dois)
        self.dois.gravar_mensagem('publicacao', {'message': 'durante a parada'}, 'bia', 'avisos')
        self.um.conexao.close()
        self.um = Banco(str(self.caminho / 'um.sqlite3'), 'server1')
        self.trocar(self.dois, self.um)
        self.assertEqual(self.um.historico('avisos')[0]['message'], 'durante a parada')
        self.assertEqual(self.um.resumo(), self.dois.resumo())

    def test_migrar_banco_antigo(self):
        self.um.conexao.close()
        conexao = sqlite3.connect(self.caminho / 'um.sqlite3')
        conexao.execute('DELETE FROM controle')
        conexao.execute('DELETE FROM registros')
        conexao.execute('INSERT INTO eventos VALUES (?, ?, ?, ?, ?, ?)',
                        ('antigo', 'canal', 'ana', 'arquivo', horario(), horario()))
        conexao.commit()
        conexao.close()
        self.um = Banco(str(self.caminho / 'um.sqlite3'), 'server1')
        self.assertEqual(self.trocar(self.um, self.dois), 1)
        self.assertIn('arquivo', self.dois.canais())

    def test_muitos_registros(self):
        for indice in range(219):
            self.um.gravar_mensagem('publicacao', {'message': str(indice)}, 'ana', 'geral')
        self.assertEqual(self.trocar(self.um, self.dois), 219)
        self.assertEqual(self.dois.resumo(), self.um.resumo())
        self.assertEqual(self.trocar(self.um, self.dois), 0)


if __name__ == '__main__':
    unittest.main()
