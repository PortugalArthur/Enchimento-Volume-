import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from dados.planejamento import carregar_planejamento
from dados.extrator import carregar_deck
from dados.leitor import Consolidado
from testes import test_extrator as fixtures


class TestPlanejamento(unittest.TestCase):
    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporario.cleanup)
        self.raiz = Path(self.temporario.name)
        (self.raiz / 'constraints').mkdir()
        self.usina = dict(id=3, reservoir={'min_storage_hm3': 60}, entry_stage_id=4,
                          filling={'start_stage_id': 2, 'filling_min_rate_m3s': 5})
        self.estagios = {s: dict(start_date=f'2026-0{s+1}-01', horas=720,
                                 blocks=[{'id': 0, 'hours': 240}, {'id': 1, 'hours': 480}])
                          for s in range(5)}

    def limites(self, linhas):
        pd.DataFrame(linhas).to_parquet(self.raiz / 'constraints/hydro_bounds.parquet', index=False)

    def carregar(self):
        return carregar_planejamento(self.raiz, {3: self.usina}, self.estagios).set_index('stage_id')

    def test_trajetoria_reproduz_valores_do_teste_oficial_v020(self):
        plano = self.carregar()
        self.assertEqual(plano.em_enchimento.tolist(), [False, False, True, True, False])
        self.assertAlmostEqual(plano.loc[2, 'filling_target_hm3'], 47.04)
        self.assertEqual(plano.loc[3, 'filling_target_hm3'], 60)
        self.assertAlmostEqual(plano.loc[2, 'volume_referencia_enchimento_hm3'], 12.96)
        self.assertTrue(plano.loc[[0, 1, 4], 'filling_target_hm3'].isna().all())
        self.assertTrue(plano.loc[[0, 1, 4], 'volume_referencia_enchimento_hm3'].isna().all())
        self.assertEqual(plano.loc[2, 'mes_referencia'], '2026-03')

    def test_overrides_esparsos_nulos_e_zero_nao_propagam_valores(self):
        self.limites([
            dict(hydro_id=3, stage_id=2, filling_min_rate_m3s=9, water_withdrawal_m3s=-4),
            dict(hydro_id=3, stage_id=3, filling_min_rate_m3s=0),
            dict(hydro_id=3, stage_id=4, filling_min_rate_m3s=None, water_withdrawal_m3s=None),
        ])
        plano = self.carregar()
        self.assertEqual(plano.loc[2, 'filling_min_rate_m3s'], 9)
        self.assertEqual(plano.loc[3, 'filling_min_rate_m3s'], 0)
        self.assertEqual(plano.loc[4, 'filling_min_rate_m3s'], 5)
        self.assertEqual(plano.loc[3, 'water_withdrawal_m3s'], 0)
        self.assertAlmostEqual(plano.loc[2, 'water_withdrawal_hm3'], -10.368)
        self.assertEqual(plano.loc[2, 'filling_target_hm3'], 60)

    def test_volume_referencia_usa_horas_do_deck_nao_dias_do_mes(self):
        self.usina['filling']['filling_min_rate_m3s'] = 100
        self.estagios[2]['horas'] = 720
        self.assertAlmostEqual(self.carregar().loc[2, 'volume_referencia_enchimento_hm3'], 259.2)
        self.estagios[2]['horas'] = 168
        self.assertAlmostEqual(self.carregar().loc[2, 'volume_referencia_enchimento_hm3'], 60.48)

    def test_limitacao_por_minimo_nao_contamina_acumulador(self):
        self.usina['filling']['start_stage_id'] = 1
        self.limites([dict(hydro_id=3, stage_id=2, min_storage_hm3=10)])
        plano = self.carregar()
        self.assertEqual(plano.loc[2, 'filling_target_hm3'], 10)
        self.assertAlmostEqual(plano.loc[1, 'filling_target_hm3'], 34.08)
        self.assertEqual(plano.loc[3, 'filling_target_hm3'], 60)

    def test_meta_negativa_e_taxa_zero_seguem_algoritmo_oficial(self):
        self.usina['filling']['filling_min_rate_m3s'] = 100
        self.assertAlmostEqual(self.carregar().loc[2, 'filling_target_hm3'], -199.2)
        del self.usina['filling']['filling_min_rate_m3s']
        plano = self.carregar()
        self.assertEqual(plano.loc[2, 'filling_target_hm3'], 60)
        self.assertEqual(plano.loc[3, 'filling_target_hm3'], 60)

    def test_usina_sem_enchimento_tem_meta_nula_nao_zero(self):
        del self.usina['filling']
        plano = self.carregar()
        self.assertFalse(plano.em_enchimento.any())
        self.assertTrue(plano.filling_target_hm3.isna().all())
        self.assertTrue(plano.volume_referencia_enchimento_hm3.isna().all())
        self.assertTrue(plano.water_withdrawal_m3s.eq(0).all())
        self.assertTrue(plano.filling_start_stage_id.isna().all())

    def test_falta_de_ancora_nao_inventa_meta(self):
        del self.estagios[3]
        with self.assertRaisesRegex(ValueError, 'falta o estágio 3'):
            self.carregar()

    def test_ids_nao_contiguos_usam_ids_originais(self):
        self.usina['filling']['start_stage_id'] = 4
        self.usina['entry_stage_id'] = 10
        self.estagios = {4: self.estagios[2], 9: self.estagios[3]}
        plano = self.carregar()
        self.assertEqual(plano.index.tolist(), [4, 9])
        self.assertAlmostEqual(plano.loc[4, 'filling_target_hm3'], 47.04)
        self.assertEqual(plano.loc[9, 'filling_target_hm3'], 60)

    def test_duplicatas_por_coluna_sao_rejeitadas_mas_linhas_disjuntas_sao_validas(self):
        self.limites([dict(hydro_id=3, stage_id=2, water_withdrawal_m3s=0),
                      dict(hydro_id=3, stage_id=2, water_withdrawal_m3s=0)])
        with self.assertRaisesRegex(ValueError, 'duplicado'):
            self.carregar()
        self.limites([dict(hydro_id=3, stage_id=2, water_withdrawal_m3s=10),
                      dict(hydro_id=3, stage_id=2, filling_min_rate_m3s=4)])
        self.assertEqual(self.carregar().loc[2, 'water_withdrawal_m3s'], 10)

    def test_limites_invalidos_nao_sao_ignorados(self):
        casos = [
            dict(hydro_id=3, stage_id=2, block_id=0, water_withdrawal_m3s=10),
            dict(hydro_id=99, stage_id=2, water_withdrawal_m3s=10),
            dict(hydro_id=3, stage_id=99, water_withdrawal_m3s=10),
            dict(hydro_id=3, stage_id=2, filling_min_rate_m3s=-1),
            dict(hydro_id=3, stage_id=2, min_storage_hm3=-1),
            dict(hydro_id=3, stage_id=2, water_withdrawal_m3s=np.inf),
        ]
        for linha in casos:
            with self.subTest(linha=linha):
                self.limites([linha])
                with self.assertRaises(ValueError):
                    self.carregar()

    def test_configuracao_invalida_e_rejeitada(self):
        for campo, valor in [('start_stage_id', 4), ('filling_min_rate_m3s', -1)]:
            with self.subTest(campo=campo):
                anterior = self.usina['filling'][campo]
                self.usina['filling'][campo] = valor
                with self.assertRaises(ValueError):
                    self.carregar()
                self.usina['filling'][campo] = anterior
        del self.usina['entry_stage_id']
        with self.assertRaises(ValueError):
            self.carregar()

    def test_integracao_preserva_cenarios_grava_proveniencia_e_exporta(self):
        fixture = fixtures.TestExtrator()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for h in fixture.usinas:
            if h['id'] == 40:
                h.update(entry_stage_id=10, filling={'start_stage_id': 4, 'filling_min_rate_m3s': 100})
        (fixture.deckpath / 'system/hydros.json').write_text(json.dumps({'hydros': fixture.usinas}))
        (fixture.deckpath / 'constraints').mkdir()
        pd.DataFrame([dict(hydro_id=40, stage_id=4, water_withdrawal_m3s=10)]).to_parquet(
            fixture.deckpath / 'constraints/hydro_bounds.parquet', index=False)
        for arquivo in fixture.hydros.glob('*/data.parquet'):
            fixture.alterar(lambda df: df.assign(storage_final_hm3=np.where(df.scenario_id == 0, 50., 65.)), arquivo)
        fixture.rodar()
        base = Consolidado.abrir(fixture.saida)
        df = base.dados.set_index(['stage_id', 'scenario_id'])
        self.assertEqual(len(df), 4)
        self.assertAlmostEqual(df.loc[(4, 0), 'filling_target_hm3'], 58.56)
        self.assertAlmostEqual(df.loc[(4, 0), 'deficit_meta_enchimento_hm3'], 8.56)
        self.assertEqual(df.loc[(4, 7), 'deficit_meta_enchimento_hm3'], 0)
        self.assertEqual(df.loc[(9, 0), 'deficit_meta_enchimento_hm3'], 10)
        self.assertEqual(df.loc[(4, 0), 'variacao_armazenamento_hm3'], 50 - 10044)
        self.assertAlmostEqual(df.loc[(4, 0), 'water_withdrawal_hm3'], .144)
        self.assertEqual(df.loc[(9, 0), 'water_withdrawal_m3s'], 0)
        self.assertTrue(base.metadados['planejamento']['hydro_bounds_presente'])
        self.assertIn('constraints/hydro_bounds.parquet', base.metadados['sha256'])
        destino = self.raiz / 'planejamento.csv'
        base.exportar(destino)
        exportado = pd.read_csv(destino, sep=';', decimal=',')
        self.assertEqual(len(exportado), 4)
        self.assertIn('mes_referencia', exportado)
        # Uma falha no deck não deve substituir uma saída já gerada.
        anterior = fixture.saida.read_bytes()
        pd.DataFrame([dict(hydro_id=40, stage_id=4, filling_min_rate_m3s=-1)]).to_parquet(
            fixture.deckpath / 'constraints/hydro_bounds.parquet', index=False)
        with self.assertRaises(ValueError):
            fixture.rodar(sobrescrever=True)
        self.assertEqual(fixture.saida.read_bytes(), anterior)


if __name__ == '__main__':
    unittest.main()
