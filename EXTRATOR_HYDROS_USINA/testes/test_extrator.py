"""Verifica contas e falhas que poderiam associar cenários ou contar água incorretamente."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from dados.extrator import (CAMPOS_ADICIONAIS, VOLUMES_ADICIONAIS, CHAVE, carregar_deck, consolidar, consolidar_cenario,
                           encontrar_cenarios, validar_selecao)


class TestExtrator(unittest.TestCase):
    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporario.cleanup)
        self.raiz = Path(self.temporario.name)
        self.hydros = self.raiz/'hydros'
        self.deckpath = self.raiz/'deck'
        (self.deckpath/'system').mkdir(parents=True)
        self.usinas = [dict(id=i, name=f'UHE {i}', downstream_id=d)
                       for i, d in [(5, 10), (10, 40), (20, 40), (40, None), (99, None)]]
        (self.deckpath/'system/hydros.json').write_text(json.dumps({'hydros': self.usinas}))
        self.stages = [dict(id=s, start_date=f'2026-0{mes}-01', end_date=f'2026-0{mes+1}-01',
                            blocks=[dict(id=b, name=str(b), hours=h) for b, h in enumerate(horas)])
                       for s, mes, horas in [(4, 1, [1, 3]), (9, 2, [3, 1])]]
        self.salvar_stages()
        for c in [0, 7]:
            linhas = []
            for s in [4, 9]:
                for hid in [5, 10, 20, 40, 99]:
                    for b in [0, 1]:
                        q, v = {10: ([10, 20], [2, 4]), 20: ([5, 9], [1, 3])}.get(hid, ([100, 200], [0, 0]))
                        linhas.append(dict(scenario_id=c, stage_id=s, node_id=s+100+c, hydro_id=hid, block_id=b,
                                           turbined_m3s=q[b]+c, spillage_m3s=v[b], incremental_inflow_m3s=1000+hid+s+c,
                                           inflow_nonnegativity_slack_m3s=float(b+4),
                                           evaporation_m3s=hid+10+20*b, diverted_inflow_m3s=2+4*b,
                                           diverted_outflow_m3s=1+2*b, storage_initial_hm3=10000+hid+s+c,
                                           storage_final_hm3=9000+hid+s+c, turbined_slack_m3s=3+4*b,
                                           outflow_slack_below_m3s=5+8*b, outflow_slack_above_m3s=7+12*b,
                                           generation_slack_mw=11+16*b, storage_violation_below_hm3=.25,
                                           filling_target_violation_hm3=.5, evaporation_violation_pos_m3s=.1+.2*b,
                                           evaporation_violation_neg_m3s=.2+.4*b,
                                           water_withdrawal_violation_pos_m3s=.3+.6*b,
                                           water_withdrawal_violation_neg_m3s=.4+.8*b))
            path=self.hydros/f'scenario_id={c:04d}'/'data.parquet'
            path.parent.mkdir(parents=True)
            pd.DataFrame(linhas).sample(frac=1, random_state=3).to_parquet(path, index=False)
        self.deck=carregar_deck(self.deckpath)
        self.arquivo=self.hydros/'scenario_id=0000/data.parquet'
        self.saida=self.raiz/'out/resultado.parquet'

    def salvar_stages(self):
        (self.deckpath/'stages.json').write_text(json.dumps({'stages': self.stages}))

    def alterar(self, func, arquivo=None):
        arquivo = arquivo or self.arquivo
        dados=pq.ParquetFile(arquivo).read().to_pandas()
        func(dados).to_parquet(arquivo, index=False)

    def rodar(self, **kwargs):
        return consolidar(self.hydros, self.deckpath, 40, [10,20], self.saida, progresso=lambda _: None, **kwargs)

    def cenario(self, ids=None, usina=40):
        return consolidar_cenario(self.arquivo, 0, self.deck, usina, [10,20] if ids is None else ids)

    def test_media_ponderada_e_multiplas_montantes(self):
        df=self.cenario().set_index('stage_id')
        self.assertAlmostEqual(df.loc[4,'agua_de_montante_m3s'],31.5)
        self.assertAlmostEqual(df.loc[9,'agua_de_montante_m3s'],22.5)
        self.assertAlmostEqual(df.loc[4,'agua_montante_uhe_10_m3s'],21)
        self.assertAlmostEqual(df.loc[4,'agua_montante_uhe_20_m3s'],10.5)
        self.assertAlmostEqual(df.loc[4,'turbined_m3s'],175)
        self.assertEqual(df.loc[4,'inflow_nonnegativity_slack_m3s'],4)
        self.assertEqual(df.loc[4,'incremental_inflow_m3s'],1044)

    def test_ids_nao_contiguos_ordenacao_e_metadados(self):
        self.rodar(cenarios_esperados=2)
        df=pq.ParquetFile(self.saida).read().to_pandas()
        self.assertEqual(list(zip(df.stage_id,df.scenario_id)),[(4,0),(4,7),(9,0),(9,7)])
        self.assertEqual(df.groupby('stage_id').size().tolist(),[2,2])
        self.assertAlmostEqual(df.loc[1,'agua_de_montante_m3s'],45.5)
        self.assertEqual(df.node_id.tolist(),[104,111,109,116])
        meta=json.loads(pq.read_metadata(self.saida).metadata[b'extrator_hydros'])
        self.assertTrue(meta['selecao_completa'])
        self.assertEqual(meta['scenario_ids'],[0,7])
        self.assertEqual(len(meta['sha256']['stages.json']),64)

    def test_cabeceira_sem_montantes(self):
        df=self.cenario([],usina=5)
        self.assertTrue(df.agua_de_montante_m3s.eq(0).all())

    def test_selecao_parcial(self):
        df=self.cenario([10])
        self.assertEqual(df.agua_de_montante_m3s.tolist(),[21,15])

    def test_novos_campos_ponderam_taxas_e_preservam_volumes_da_usina(self):
        self.rodar()
        df = pq.ParquetFile(self.saida).read().to_pandas()
        linha = df[(df.stage_id == 4) & (df.scenario_id == 0)].iloc[0]
        esperados = dict(evaporation_m3s=65, diverted_inflow_m3s=5, diverted_outflow_m3s=2.5,
                         storage_initial_hm3=10044, storage_final_hm3=9044, turbined_slack_m3s=6,
                         outflow_slack_below_m3s=11, outflow_slack_above_m3s=16, generation_slack_mw=23,
                         storage_violation_below_hm3=.25, filling_target_violation_hm3=.5,
                         evaporation_violation_pos_m3s=.25, evaporation_violation_neg_m3s=.5,
                         water_withdrawal_violation_pos_m3s=.75, water_withdrawal_violation_neg_m3s=1)
        self.assertEqual(set(esperados), set(CAMPOS_ADICIONAIS))
        for campo, valor in esperados.items():
            with self.subTest(campo=campo):
                self.assertAlmostEqual(linha[campo], valor)
        outra = df[(df.stage_id == 9) & (df.scenario_id == 0)].iloc[0]
        self.assertAlmostEqual(outra.evaporation_m3s, 55)
        self.assertAlmostEqual(outra.generation_slack_mw, 15)
        meta = json.loads(pq.read_metadata(self.saida).metadata[b'extrator_hydros'])
        self.assertEqual(meta['versao'], 2)
        self.assertEqual(meta['unidades_por_coluna']['storage_initial_hm3'], 'hm3')
        self.assertEqual(meta['unidades_por_coluna']['generation_slack_mw'], 'MW')
        self.assertEqual(meta['unidades_por_coluna']['evaporation_m3s'], 'm3/s')

    def test_novos_campos_sem_patamares_sao_copiados(self):
        self.alterar(lambda df: df[df.block_id == 0].assign(block_id=np.nan))
        original = pq.ParquetFile(self.arquivo).read().to_pandas()
        esperado = original[original.hydro_id == 40].set_index('stage_id')[CAMPOS_ADICIONAIS].sort_index()
        obtido = self.cenario().set_index('stage_id')[CAMPOS_ADICIONAIS]
        pd.testing.assert_frame_equal(obtido, esperado)

    def test_volume_divergente_entre_patamares_e_rejeitado(self):
        original = self.arquivo.read_bytes()
        for coluna in VOLUMES_ADICIONAIS:
            with self.subTest(coluna=coluna):
                self.arquivo.write_bytes(original)
                self.alterar(lambda df: df.assign(**{coluna: df[coluna]+df.block_id}))
                with self.assertRaisesRegex(ValueError, coluna + ' diverge'):
                    self.cenario()

    def test_novos_campos_nao_aceitam_nao_finitos(self):
        original = self.arquivo.read_bytes()
        for coluna in CAMPOS_ADICIONAIS:
            with self.subTest(coluna=coluna):
                self.arquivo.write_bytes(original)
                self.alterar(lambda df: df.assign(**{coluna: np.where(df.hydro_id == 40, np.nan, df[coluna])}))
                with self.assertRaisesRegex(ValueError, coluna):
                    self.cenario()

    def test_campo_novo_ausente_preserva_saida_anterior(self):
        self.rodar()
        anterior = self.saida.read_bytes()
        self.alterar(lambda df: df.drop(columns=['storage_initial_hm3']))
        with self.assertRaisesRegex(ValueError, 'colunas ausentes.*storage_initial_hm3'):
            self.rodar(sobrescrever=True)
        self.assertEqual(self.saida.read_bytes(), anterior)

    def test_rejeita_ancestral_e_usina_analisada(self):
        for ids in [[5],[40],[10,10],[99]]:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                validar_selecao(self.deck,40,ids)

    def test_rejeita_patamar_ausente(self):
        self.alterar(lambda df:df.drop(df[(df.hydro_id==10)&(df.stage_id==4)&(df.block_id==1)].index))
        with self.assertRaisesRegex(ValueError,'patamares ausentes'):
            self.cenario()

    def test_rejeita_usina_ausente(self):
        self.alterar(lambda df:df[df.hydro_id!=20])
        with self.assertRaisesRegex(ValueError,'ausente ou divergente'):
            self.cenario()

    def test_rejeita_no_diferente(self):
        self.alterar(lambda df:df.assign(node_id=np.where(df.hydro_id==10,999,df.node_id)))
        with self.assertRaisesRegex(ValueError,'ausente ou divergente'):
            self.cenario()

    def test_rejeita_cenario_diferente(self):
        self.alterar(lambda df:df.assign(scenario_id=999))
        with self.assertRaisesRegex(ValueError,'scenario_id diferente'):
            self.cenario()

    def test_rejeita_duplicidade(self):
        self.alterar(lambda df:pd.concat([df,df[df.hydro_id==10].head(1)]))
        with self.assertRaisesRegex(ValueError,'duplicada'):
            self.cenario()

    def test_rejeita_nao_finito(self):
        self.alterar(lambda df:df.assign(turbined_m3s=np.where(df.hydro_id==10,np.nan,df.turbined_m3s)))
        with self.assertRaisesRegex(ValueError,'não finita'):
            self.cenario()

    def test_rejeita_incremental_divergente(self):
        self.alterar(lambda df:df.assign(incremental_inflow_m3s=df.incremental_inflow_m3s+df.block_id))
        with self.assertRaisesRegex(ValueError,'incremental diverge'):
            self.cenario()

    def test_nao_soma_linha_resumo_com_patamares(self):
        def adicionar(df):
            resumo=df[df.block_id==0].copy()
            resumo['block_id']=np.nan
            resumo['turbined_m3s']=99999
            resumo['evaporation_m3s']=99999
            resumo['storage_initial_hm3']=99999
            return pd.concat([df,resumo])
        self.alterar(adicionar)
        self.assertAlmostEqual(self.cenario().iloc[0].agua_de_montante_m3s,31.5)
        self.assertAlmostEqual(self.cenario().iloc[0].evaporation_m3s,65)
        self.assertEqual(self.cenario().iloc[0].storage_initial_hm3,10044)

    def test_linha_de_estagio_sem_patamares(self):
        self.alterar(lambda df:df[df.block_id==0].assign(block_id=np.nan))
        self.assertAlmostEqual(self.cenario().iloc[0].agua_de_montante_m3s,18)

    def test_conserva_saida_anterior_se_falhar(self):
        self.saida.parent.mkdir()
        self.saida.write_bytes(b'saida anterior')
        self.alterar(lambda df:df[df.hydro_id!=20])
        with self.assertRaises(ValueError):
            self.rodar(sobrescrever=True)
        self.assertEqual(self.saida.read_bytes(),b'saida anterior')
        self.assertEqual(list(self.saida.parent.glob('*.tmp')),[])

    def test_rejeita_quantidade_cenarios_e_sobrescrita(self):
        with self.assertRaisesRegex(ValueError,'Esperados 2000'):
            self.rodar(cenarios_esperados=2000)
        self.rodar()
        with self.assertRaisesRegex(ValueError,'já existe'):
            self.rodar()

    def test_rejeita_estagio_ausente_em_cenario(self):
        arquivo=self.hydros/'scenario_id=0007/data.parquet'
        self.alterar(lambda df:df[df.stage_id!=9],arquivo)
        with self.assertRaisesRegex(ValueError,'difere do primeiro'):
            self.rodar()

    def test_rejeita_pastas_cenarios_duplicadas(self):
        pasta=self.hydros/'scenario_id=0'
        pasta.mkdir()
        (pasta/'data.parquet').write_bytes(self.arquivo.read_bytes())
        with self.assertRaisesRegex(ValueError,'duplicado'):
            encontrar_cenarios(self.hydros)

    def test_rejeita_horas_invalidas(self):
        self.stages[0]['blocks'][0]['hours']=0
        self.salvar_stages()
        with self.assertRaisesRegex(ValueError,'duração inválida'):
            carregar_deck(self.deckpath)


if __name__=='__main__':
    unittest.main()
