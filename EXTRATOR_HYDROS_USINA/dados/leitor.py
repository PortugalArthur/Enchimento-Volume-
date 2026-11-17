"""Leitura e consultas dos consolidados HYDROS, sem depender do deck original."""
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from dados.planejamento import NULOS_FORA_ENCHIMENTO


ROTULOS = {
    'agua_de_montante_m3s': 'Água de montante',
    'incremental_inflow_m3s': 'Vazão incremental local',
    'turbined_m3s': 'Vazão turbinada da usina',
    'spillage_m3s': 'Vazão vertida da usina',
    'outflow_m3s': 'Vazão de saída da usina',
    'agua_montante_turbinada_m3s': 'Montante — turbinada',
    'agua_montante_vertida_m3s': 'Montante — vertida',
    'inflow_nonnegativity_slack_m3s': 'Slack de não negatividade',
    'evaporation_m3s': 'Evaporação',
    'diverted_inflow_m3s': 'Vazão de desvio recebida',
    'diverted_outflow_m3s': 'Vazão de desvio enviada',
    'storage_initial_hm3': 'Volume armazenado inicial',
    'storage_final_hm3': 'Volume armazenado final',
    'turbined_slack_m3s': 'Slack de turbinamento',
    'outflow_slack_below_m3s': 'Slack de defluência abaixo do limite',
    'outflow_slack_above_m3s': 'Slack de defluência acima do limite',
    'generation_slack_mw': 'Slack de geração',
    'storage_violation_below_hm3': 'Violação do armazenamento mínimo',
    'filling_target_violation_hm3': 'Violação da meta de enchimento',
    'evaporation_violation_pos_m3s': 'Violação positiva de evaporação',
    'evaporation_violation_neg_m3s': 'Violação negativa de evaporação',
    'water_withdrawal_violation_pos_m3s': 'Violação positiva de retirada de água',
    'water_withdrawal_violation_neg_m3s': 'Violação negativa de retirada de água',
    'filling_min_rate_m3s': 'Taxa mínima de enchimento',
    'volume_referencia_enchimento_hm3': 'Volume de referência de enchimento',
    'filling_target_hm3': 'Meta de armazenamento no enchimento',
    'water_withdrawal_m3s': 'Retirada de água programada',
    'water_withdrawal_hm3': 'Volume de retirada programada',
    'min_storage_hm3': 'Volume mínimo operacional',
    'variacao_armazenamento_hm3': 'Variação do armazenamento',
    'deficit_meta_enchimento_hm3': 'Déficit em relação à meta de enchimento',
    'horas_estagio': 'Duração do estágio',
}


def unidade(coluna):
    if coluna == 'horas_estagio':
        return 'h'
    if coluna.endswith('_hm3'):
        return 'hm³'
    if coluna.endswith('_mw'):
        return 'MW'
    return 'm³/s'


def rotulo(coluna):
    if coluna.startswith('agua_montante_uhe_'):
        return f"Contribuição da UHE {coluna.removeprefix('agua_montante_uhe_').removesuffix('_m3s')}"
    return ROTULOS.get(coluna, coluna)


@dataclass
class Consolidado:
    caminho: Path
    dados: pd.DataFrame
    metadados: dict
    metricas: list[str]

    @classmethod
    def abrir(cls, caminho):
        caminho = Path(caminho)
        tabela = pq.ParquetFile(caminho).read()
        df = tabela.to_pandas()
        if df.empty:
            raise ValueError('O arquivo não contém observações.')
        for coluna in ['scenario_id', 'stage_id', 'hydro_id']:
            if coluna not in df:
                raise ValueError(f'Este não é um consolidado HYDROS: falta {coluna}.')
            if not pd.api.types.is_integer_dtype(df[coluna]) or df[coluna].isna().any():
                raise ValueError(f'A coluna {coluna} deve conter IDs inteiros preenchidos.')
        if df.hydro_id.nunique() != 1:
            raise ValueError('Selecione um consolidado de uma única usina.')
        if df.duplicated(['scenario_id', 'stage_id']).any():
            raise ValueError('Há observações duplicadas para o mesmo cenário e estágio.')
        metricas = [c for c in ROTULOS if c in df]
        metricas += [c for c in df if c.startswith('agua_montante_uhe_') and c.endswith('_m3s')]
        if not metricas:
            raise ValueError('Não foram encontradas grandezas reconhecidas.')
        for c in metricas:
            nulos = df[c].isna()
            if nulos.any():
                permitido = (c in NULOS_FORA_ENCHIMENTO and 'em_enchimento' in df
                             and pd.api.types.is_bool_dtype(df.em_enchimento)
                             and not df.em_enchimento.isna().any()
                             and not df.loc[nulos, 'em_enchimento'].any())
                if not permitido:
                    raise ValueError(f'A coluna {c} contém valores ausentes fora da regra de aplicabilidade.')
            if not pd.api.types.is_numeric_dtype(df[c]) or not np.isfinite(df[c].dropna()).all():
                raise ValueError(f'A coluna {c} contém valores ausentes, não numéricos ou não finitos.')
        bruto = (tabela.schema.metadata or {}).get(b'extrator_hydros')
        meta = json.loads(bruto) if bruto else {}
        if not isinstance(meta, dict):
            raise ValueError('Metadados extrator_hydros inválidos.')
        return cls(caminho, df.sort_values(['stage_id', 'scenario_id']).reset_index(drop=True), meta, metricas)

    def filtrar(self, cenario=None, estagio=None):
        df = self.dados
        if cenario is not None:
            df = df[df.scenario_id == cenario]
        if estagio is not None:
            df = df[df.stage_id == estagio]
        return df

    def resumo(self, metrica, cenario=None, estagio=None):
        grupos = self.filtrar(cenario, estagio).groupby('stage_id')[metrica]
        return grupos.agg(media='mean', p10=lambda s: s.quantile(.1),
                          mediana='median', p90=lambda s: s.quantile(.9))

    def exportar(self, destino, cenario=None, estagio=None):
        destino = Path(destino)
        if destino.resolve() == self.caminho.resolve():
            raise ValueError('O arquivo Parquet original não pode ser substituído.')
        # Separador e BOM facilitam abrir no Excel em português. Modo x protege saídas existentes.
        self.filtrar(cenario, estagio).to_csv(destino, index=False, sep=';', decimal=',',
                                             encoding='utf-8-sig', mode='x')
