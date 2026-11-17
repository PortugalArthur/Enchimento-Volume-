import base64
import gzip
import json
from pathlib import Path
import re
import tempfile
import unittest

import numpy as np
import pandas as pd

from dados.leitor import Consolidado
from dados.grafico_html import gerar_html, preparar_dados


class TestGraficoHTML(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raiz = Path(self.temp.name)
        # Vazões já ponderadas: 100 h a 10 e 300 h a 30 -> 25 m³/s, não soma 40.
        linhas = []
        for c in [7, 0]:
            for s in [9, 4]:
                linhas.append(dict(scenario_id=c, stage_id=s, hydro_id=40, horas_estagio=400.,
                    agua_montante_turbinada_m3s=25., agua_montante_vertida_m3s=5.,
                    incremental_inflow_m3s=10.+c, inflow_nonnegativity_slack_m3s=2.,
                    turbined_m3s=8., spillage_m3s=3., water_withdrawal_m3s=-4.,
                    water_withdrawal_violation_neg_m3s=1.5, evaporation_m3s=-.5,
                    em_enchimento=s==4, filling_target_hm3=60. if s==4 else np.nan,
                    filling_target_violation_hm3=12., data_inicio='2026-01-01' if s==4 else '2026-02-01'))
        self.arquivo = self.raiz/'teste.parquet'
        pd.DataFrame(linhas).to_parquet(self.arquivo, index=False)
        self.base = Consolidado.abrir(self.arquivo)

    def test_oito_series_convertidas_com_sinais_e_meta_sem_dupla_conversao(self):
        dados = preparar_dados(self.base)
        self.assertEqual(list(dados['cenarios']), ['0', '7'])
        c = dados['cenarios']['0']
        self.assertEqual(c['estagios'], [4,9])
        self.assertEqual(len(c['series']),8)
        esperados = [60.48,11.52,4.32,60.,-5.76,12.,2.16,-.72]
        for serie, esperado in zip(c['series'],esperados):
            self.assertAlmostEqual(serie[0],esperado)
        self.assertIsNone(c['series'][3][1])
        self.assertAlmostEqual(dados['cenarios']['7']['series'][0][0],70.56)

    def test_html_tem_todos_cenarios_mesmo_se_inicia_em_um_e_preserva_arquivos(self):
        destino = self.raiz/'grafico.html'
        gerar_html(self.base,destino,7)
        html = destino.read_text()
        payload = re.search(r'<script id="payload"[^>]*>(.*?)</script>',html,re.S).group(1)
        dados = json.loads(gzip.decompress(base64.b64decode(payload)))
        self.assertEqual(dados['cenario_inicial'],'7')
        self.assertEqual(len(dados['cenarios']),2)
        self.assertIn('Plotly.newPlot',html)
        with self.assertRaises(FileExistsError):
            gerar_html(self.base,destino)
        with self.assertRaisesRegex(ValueError,'Cenário'):
            gerar_html(self.base,self.raiz/'invalido.html',3)
        self.assertFalse((self.raiz/'invalido.html').exists())

    def test_parquet_antigo_sem_horas_e_rejeitado_sem_inferir_duracao(self):
        self.base.dados = self.base.dados.drop(columns=['horas_estagio'])
        with self.assertRaisesRegex(ValueError,'Gere novamente'):
            preparar_dados(self.base)

    def test_rejeita_duracao_invalida_e_informa_montante_parcial(self):
        self.base.metadados['selecao_completa'] = False
        self.assertTrue(preparar_dados(self.base)['parcial'])
        self.base.dados.loc[0,'horas_estagio']=0
        with self.assertRaisesRegex(ValueError,'positivas'):
            preparar_dados(self.base)


if __name__ == '__main__':
    unittest.main()
