"""Gráfico autônomo, com um cenário por vez e todas as séries em hm³."""
import base64
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from dados.leitor import Consolidado


SERIES = [
    ('Vazão afluente', '#2563eb'), ('Turbinada pela usina', '#0891b2'),
    ('Vertida pela usina', '#f59e0b'), ('Meta de enchimento', '#7c3aed'),
    ('Retirada programada', '#dc2626'), ('Folga da meta de enchimento', '#db2777'),
    ('Folga de retirada para menos', '#16a34a'), ('Evaporação efetiva', '#64748b'),
]
VAZOES = ['agua_montante_turbinada_m3s', 'agua_montante_vertida_m3s',
          'incremental_inflow_m3s', 'inflow_nonnegativity_slack_m3s',
          'turbined_m3s', 'spillage_m3s', 'water_withdrawal_m3s',
          'water_withdrawal_violation_neg_m3s', 'evaporation_m3s']


def preparar_dados(base):
    df = base.dados
    faltantes = set(VAZOES + ['horas_estagio', 'filling_target_hm3', 'filling_target_violation_hm3']) - set(df)
    if faltantes:
        raise ValueError('O consolidado não contém: ' + ', '.join(sorted(faltantes))
                         + '. Gere novamente o Parquet com o extrator atualizado e o deck completo.')
    if not pd.api.types.is_numeric_dtype(df.horas_estagio) or not np.isfinite(df.horas_estagio).all() or not df.horas_estagio.gt(0).all():
        raise ValueError('horas_estagio deve conter durações finitas e positivas.')
    if not df.groupby('stage_id').horas_estagio.nunique().eq(1).all():
        raise ValueError('A duração do estágio diverge entre cenários.')
    for c in VAZOES + ['filling_target_violation_hm3']:
        if not pd.api.types.is_numeric_dtype(df[c]) or not np.isfinite(df[c]).all():
            raise ValueError(f'Valores inválidos em {c}.')
    fator = df.horas_estagio * .0036
    afluente = df[VAZOES[:4]].sum(axis=1) * fator
    valores = [afluente, df.turbined_m3s * fator, df.spillage_m3s * fator,
               df.filling_target_hm3, df.water_withdrawal_m3s * fator,
               df.filling_target_violation_hm3, df.water_withdrawal_violation_neg_m3s * fator,
               df.evaporation_m3s * fator]
    for v in valores:
        if not np.isfinite(v.dropna()).all():
            raise ValueError('A conversão para volume produziu valor não finito.')
    cenarios = {}
    for cid, grupo in df.groupby('scenario_id', sort=True):
        grupo = grupo.sort_values('stage_id')
        indices = grupo.index
        cenarios[str(int(cid))] = dict(
            estagios=[int(v) for v in grupo.stage_id],
            datas=[str(v) for v in grupo.data_inicio] if 'data_inicio' in grupo else [''] * len(grupo),
            series=[[None if pd.isna(v) else float(v) for v in serie.loc[indices]] for serie in valores],
        )
    nome = base.metadados.get('nome_usina')
    if not nome:
        nome = str(df.nome_usina.iloc[0]) if 'nome_usina' in df else f'UHE {df.hydro_id.iloc[0]}'
    return dict(nome=nome, arquivo=base.caminho.name, hydro_id=int(df.hydro_id.iloc[0]),
                parcial=base.metadados.get('selecao_completa') is False,
                linhas=len(df), definicoes=SERIES, cenarios=cenarios)


def gerar_html(base: Consolidado, destino, cenario=None):
    from plotly.offline import get_plotlyjs

    dados = preparar_dados(base)
    if cenario is not None and str(cenario) not in dados['cenarios']:
        raise ValueError(f'Cenário {cenario} não está no Parquet.')
    dados['cenario_inicial'] = str(cenario) if cenario is not None else next(iter(dados['cenarios']))
    payload = base64.b64encode(gzip.compress(json.dumps(dados, ensure_ascii=False, allow_nan=False,
                                                     separators=(',', ':')).encode('utf-8'), mtime=0)).decode('ascii')
    modelo = Path(__file__).resolve().parents[1] / 'aplicacao/templates/grafico.html'
    html = modelo.read_text(encoding='utf-8').replace('__DADOS_COMPACTADOS__', payload).replace('__PLOTLY_JS__', get_plotlyjs())
    destino = Path(destino)
    if destino.suffix.lower() != '.html':
        raise ValueError('Escolha um arquivo com extensão .html.')
    # Não altera o original nem substitui um HTML anterior.
    with destino.open('x', encoding='utf-8') as f:
        f.write(html)
    return destino
