"""Resolve parâmetros de estágio e reproduz a meta do Novo Modelo v0.20.0."""
from numbers import Real

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ARQUIVO_LIMITES = 'constraints/hydro_bounds.parquet'
COLUNAS_LIMITES = ['min_storage_hm3', 'filling_min_rate_m3s', 'water_withdrawal_m3s']
NULOS_FORA_ENCHIMENTO = {
    'volume_referencia_enchimento_hm3', 'filling_target_hm3', 'deficit_meta_enchimento_hm3',
}
FONTE_META = ('https://github.com/ons-ccee-epe/novomodelo/blob/v0.20.0/'
              'crates/novomodelo-sddp/src/setup/lp_build_inputs.rs')


def _numero(valor, campo, nao_negativo=False):
    if isinstance(valor, (bool, np.bool_)) or not isinstance(valor, Real) or not np.isfinite(valor):
        raise ValueError(f'{campo}: esperado número finito, recebido {valor!r}.')
    if nao_negativo and valor < 0:
        raise ValueError(f'{campo} não pode ser negativo.')
    return float(valor)


def _id(valor, campo):
    numero = _numero(valor, campo)
    if numero % 1:
        raise ValueError(f'{campo} deve ser um ID inteiro.')
    return int(numero)


def _overrides(pasta, usinas, estagios):
    arquivo = pasta / ARQUIVO_LIMITES
    if not arquivo.exists():
        return {}
    esquema = pq.read_schema(arquivo).names
    if not {'hydro_id', 'stage_id'}.issubset(esquema):
        raise ValueError(f'{ARQUIVO_LIMITES}: faltam hydro_id ou stage_id.')
    colunas = ['hydro_id', 'stage_id'] + [c for c in ['block_id', *COLUNAS_LIMITES] if c in esquema]
    df = pq.ParquetFile(arquivo).read(columns=colunas).to_pandas()
    valores = {}
    for linha in df.to_dict('records'):
        hid = _id(linha['hydro_id'], 'hydro_id dos limites')
        sid = _id(linha['stage_id'], 'stage_id dos limites')
        if hid not in usinas or sid not in estagios:
            raise ValueError(f'{ARQUIVO_LIMITES}: referência desconhecida à UHE {hid}, estágio {sid}.')
        bloco = linha.get('block_id')
        if bloco is not None and not pd.isna(bloco):
            bid = _id(bloco, 'block_id dos limites')
            if bid not in {b['id'] for b in estagios[sid]['blocks']}:
                raise ValueError(f'{ARQUIVO_LIMITES}: block_id inválido no estágio {sid}.')
        for campo in COLUNAS_LIMITES:
            valor = linha.get(campo)
            if valor is None or pd.isna(valor):
                continue  # Null não sobrescreve o padrão nem herda o estágio anterior.
            if bloco is not None and not pd.isna(bloco):
                raise ValueError(f'{ARQUIVO_LIMITES}: {campo} é parâmetro de estágio; block_id deve ser nulo.')
            chave = (hid, sid, campo)
            if chave in valores:
                raise ValueError(f'{ARQUIVO_LIMITES}: valor duplicado para UHE {hid}, estágio {sid}, {campo}.')
            valores[chave] = _numero(valor, campo, nao_negativo=campo != 'water_withdrawal_m3s')
    return valores


def carregar_planejamento(pasta, usinas, estagios):
    overrides = _overrides(pasta, usinas, estagios)
    linhas = []
    for hid, usina in usinas.items():
        minimo = _numero(usina.get('reservoir', {}).get('min_storage_hm3'),
                         f'min_storage_hm3 da UHE {hid}', nao_negativo=True)
        filling = usina.get('filling')
        inicio = entrada = None
        taxa_base = 0.0
        if filling is not None:
            if not isinstance(filling, dict):
                raise ValueError(f'filling inválido na UHE {hid}.')
            inicio = _id(filling.get('start_stage_id'), f'filling.start_stage_id da UHE {hid}')
            entrada = _id(usina.get('entry_stage_id'), f'entry_stage_id da UHE {hid}')
            if inicio < 0 or entrada <= inicio:
                raise ValueError(f'Período de enchimento inválido na UHE {hid}: início deve ser >= 0 e anterior à entrada.')
            taxa_base = _numero(filling.get('filling_min_rate_m3s', 0.0),
                                f'filling_min_rate_m3s da UHE {hid}', nao_negativo=True)
        elif usina.get('entry_stage_id') is not None:
            entrada = _id(usina['entry_stage_id'], f'entry_stage_id da UHE {hid}')
        por_estagio = {}
        for sid, estagio in sorted(estagios.items()):
            em_enchimento = inicio is not None and inicio <= sid < entrada
            horas = estagio['horas']
            taxa = overrides.get((hid, sid, 'filling_min_rate_m3s'), taxa_base)
            retirada = overrides.get((hid, sid, 'water_withdrawal_m3s'), 0.0)
            volume_ref = taxa * (horas * .0036) if em_enchimento else np.nan
            volume_retirada = retirada * (horas * .0036)
            if not np.isfinite(volume_retirada) or (em_enchimento and not np.isfinite(volume_ref)):
                raise ValueError(f'Conversão para volume não finita na UHE {hid}, estágio {sid}.')
            por_estagio[sid] = dict(
                hydro_id=hid, stage_id=sid, em_enchimento=em_enchimento,
                filling_start_stage_id=inicio, entry_stage_id=entrada,
                mes_referencia=estagio['start_date'][:7], horas_estagio=horas,
                min_storage_hm3=overrides.get((hid, sid, 'min_storage_hm3'), minimo),
                filling_min_rate_m3s=taxa, volume_referencia_enchimento_hm3=volume_ref,
                filling_target_hm3=np.nan, water_withdrawal_m3s=retirada,
                water_withdrawal_hm3=volume_retirada,
            )
        ativos = [sid for sid, linha in por_estagio.items() if linha['em_enchimento']]
        if ativos:
            ultimo = entrada - 1
            if ultimo not in por_estagio:
                raise ValueError(f'UHE {hid}: falta o estágio {ultimo} (entry_stage_id - 1) em stages.json; '
                                 'não é possível reconstruir a meta de enchimento com este horizonte.')
            # Algoritmo oficial: running NÃO recebe o valor limitado de cada estágio.
            # IDs ausentes não têm duração/taxa a subtrair. Não limita a meta em zero.
            acumulado = por_estagio[ultimo]['min_storage_hm3']
            for sid in reversed(ativos):
                linha = por_estagio[sid]
                linha['filling_target_hm3'] = min(acumulado, linha['min_storage_hm3'])
                acumulado -= linha['volume_referencia_enchimento_hm3']
                if not np.isfinite(acumulado):
                    raise ValueError(f'Meta de enchimento não finita na UHE {hid}, estágio {sid}.')
        linhas.extend(por_estagio.values())
    df = pd.DataFrame(linhas)
    for coluna in ['filling_start_stage_id', 'entry_stage_id']:
        df[coluna] = df[coluna].astype('Int64')
    return df
