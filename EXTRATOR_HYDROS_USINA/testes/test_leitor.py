import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from dados.leitor import Consolidado


class TestLeitor(unittest.TestCase):
    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporario.cleanup)
        self.raiz = Path(self.temporario.name)
        self.arquivo = self.raiz / 'teste.parquet'
        self.df = pd.DataFrame({'scenario_id': [7, 0, 7, 0], 'stage_id': [9, 4, 4, 9],
                                'hydro_id': [40] * 4, 'agua_de_montante_m3s': [80., 10., 30., 40.]})
        self.salvar()

    def salvar(self):
        tabela = pa.Table.from_pandas(self.df)
        meta = {**tabela.schema.metadata, b'extrator_hydros': json.dumps({'nome_usina': 'UHE teste', 'selecao_completa': False}).encode()}
        pq.write_table(tabela.replace_schema_metadata(meta), self.arquivo)

    def test_ordena_filtra_e_calcula_percentis_sem_renumerar(self):
        base = Consolidado.abrir(self.arquivo)
        self.assertEqual(base.dados.scenario_id.tolist(), [0, 7, 0, 7])
        self.assertEqual(base.filtrar(7, 9).agua_de_montante_m3s.tolist(), [80.])
        resumo = base.resumo('agua_de_montante_m3s')
        self.assertEqual(resumo.loc[4, 'media'], 20)
        self.assertEqual(resumo.loc[4, 'p10'], 12)
        self.assertEqual(resumo.loc[4, 'p90'], 28)
        self.assertEqual(base.resumo('agua_de_montante_m3s', 7).loc[9, 'media'], 80)
        self.assertFalse(base.metadados['selecao_completa'])

    def test_exporta_filtro_completo_e_preserva_arquivos(self):
        base = Consolidado.abrir(self.arquivo)
        original = self.arquivo.read_bytes()
        destino = self.raiz / 'saida.csv'
        base.exportar(destino, 7)
        csv = pd.read_csv(destino, sep=';', decimal=',', encoding='utf-8-sig')
        self.assertEqual(csv.stage_id.tolist(), [4, 9])
        self.assertEqual(csv.agua_de_montante_m3s.tolist(), [30., 80.])
        with self.assertRaises(FileExistsError):
            base.exportar(destino)
        with self.assertRaises(ValueError):
            base.exportar(self.arquivo)
        self.assertEqual(self.arquivo.read_bytes(), original)

    def test_rejeita_duplicatas_nulos_e_multiplas_usinas(self):
        for coluna, valores in [('stage_id', [9, 9, 9, 9]),
                                ('hydro_id', [40, 41, 40, 40]),
                                ('agua_de_montante_m3s', [None, 10., 30., 40.])]:
            with self.subTest(coluna=coluna):
                original = self.df.copy()
                self.df[coluna] = valores
                self.salvar()
                with self.assertRaises(ValueError):
                    Consolidado.abrir(self.arquivo)
                self.df = original

    def test_arquivo_sem_metadados_e_filtro_vazio(self):
        self.df.to_parquet(self.arquivo, index=False)
        base = Consolidado.abrir(self.arquivo)
        self.assertEqual(base.metadados, {})
        self.assertTrue(base.filtrar(123).empty)
        self.assertTrue(base.resumo('agua_de_montante_m3s', 123).empty)

    def test_abre_exemplo_real_sem_deck_original(self):
        base = Consolidado.abrir(Path(__file__).resolve().parents[1] / 'outputs/validacao_furnas_v20_2000_cenarios.parquet')
        self.assertEqual(len(base.dados), 144000)
        self.assertEqual(len(base.resumo('agua_de_montante_m3s')), 72)
        self.assertEqual(len(base.filtrar(0)), 72)
        self.assertEqual(len(base.filtrar(estagio=0)), 2000)


if __name__ == '__main__':
    unittest.main()
