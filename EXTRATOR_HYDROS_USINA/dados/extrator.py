"""Extrai uma UHE e calcula a contribuição das montantes diretas por cenário/estágio."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from dados.planejamento import ARQUIVO_LIMITES, FONTE_META, carregar_planejamento

CHAVE = ['scenario_id', 'stage_id', 'node_id', 'hydro_id']
TEMPO = ['scenario_id', 'stage_id', 'node_id']
VAZOES = ['turbined_m3s', 'spillage_m3s']
INCREMENTAL = 'incremental_inflow_m3s'
SLACK = 'inflow_nonnegativity_slack_m3s'
TAXAS_ADICIONAIS = [
    'evaporation_m3s', 'diverted_inflow_m3s', 'diverted_outflow_m3s',
    'turbined_slack_m3s', 'outflow_slack_below_m3s', 'outflow_slack_above_m3s',
    'generation_slack_mw', 'evaporation_violation_pos_m3s',
    'evaporation_violation_neg_m3s', 'water_withdrawal_violation_pos_m3s',
    'water_withdrawal_violation_neg_m3s',
]
VOLUMES_ADICIONAIS = [
    'storage_initial_hm3', 'storage_final_hm3',
    'storage_violation_below_hm3', 'filling_target_violation_hm3',
]
CAMPOS_ADICIONAIS = TAXAS_ADICIONAIS + VOLUMES_ADICIONAIS
COLUNAS = CHAVE + ['block_id', INCREMENTAL, SLACK] + VAZOES + CAMPOS_ADICIONAIS


def _consolidar_campos_adicionais(dados, usina, deck):
    """Taxas viram médias temporais; volumes de estágio são copiados sem soma."""
    alvo = dados.loc[dados.hydro_id.eq(usina)]
    for coluna in CAMPOS_ADICIONAIS:
        if not pd.api.types.is_numeric_dtype(alvo[coluna]) or not np.isfinite(alvo[coluna]).all():
            raise ValueError(f'Valor ausente, não numérico ou não finito em {coluna} da UHE {usina}.')
    blocos = alvo.loc[alvo.block_id.notna()]
    if blocos.empty:
        return alvo[CHAVE + CAMPOS_ADICIONAIS].copy()
    for coluna in VOLUMES_ADICIONAIS:
        if not blocos.groupby(CHAVE, sort=False)[coluna].nunique().eq(1).all():
            raise ValueError(f'{coluna} diverge entre patamares da UHE {usina}; '
                             'não é possível preservar um único volume por estágio.')
    volumes = blocos.loc[blocos.block_id.eq(0), CHAVE + VOLUMES_ADICIONAIS]
    ponderados = blocos.merge(deck.pesos, on=['stage_id', 'block_id'], validate='m:1')
    ponderados[TAXAS_ADICIONAIS] = ponderados[TAXAS_ADICIONAIS].mul(ponderados.peso, axis=0)
    medias = ponderados.groupby(CHAVE, sort=False, as_index=False)[TAXAS_ADICIONAIS].sum()
    return volumes.merge(medias, on=CHAVE, validate='1:1')


@dataclass
class Deck:
    pasta: Path
    usinas: dict[int, dict]
    estagios: dict[int, dict]
    pesos: pd.DataFrame
    planejamento: pd.DataFrame

    def montantes_diretas(self, usina: int) -> list[int]:
        return sorted(i for i, h in self.usinas.items() if h.get('downstream_id') == usina)


def _inteiro(valor, campo):
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f'{campo} deve ser um inteiro: {valor!r}')
    return valor


def carregar_deck(pasta: Path | str) -> Deck:
    pasta = Path(pasta).resolve()
    arquivos = [pasta/'system/hydros.json', pasta/'stages.json']
    for arquivo in arquivos:
        if not arquivo.is_file():
            raise ValueError(f'Selecione a raiz do deck de entrada. Arquivo ausente: {arquivo}')
    hydros, stages = [json.loads(p.read_text(encoding='utf-8-sig')) for p in arquivos]
    usinas, estagios, pesos = {}, {}, []
    for h in hydros['hydros']:
        hid = _inteiro(h['id'], 'hydro_id')
        if hid in usinas or not h.get('name'):
            raise ValueError(f'UHE duplicada ou sem nome: {hid}')
        usinas[hid] = h
    for hid, h in usinas.items():
        proximo = h.get('downstream_id')
        if proximo is not None and (type(proximo) is not int or proximo not in usinas):
            raise ValueError(f'Jusante inválida da UHE {hid}: {proximo}')
        visitados, atual = set(), hid
        while atual is not None:
            if atual in visitados:
                raise ValueError(f'Ciclo na cascata hidráulica da UHE {hid}.')
            visitados.add(atual)
            atual = usinas[atual].get('downstream_id')
    for s in stages['stages']:
        sid = _inteiro(s['id'], 'stage_id')
        if sid in estagios:
            raise ValueError(f'Estágio duplicado: {sid}')
        inicio, fim = date.fromisoformat(s['start_date']), date.fromisoformat(s['end_date'])
        if fim <= inicio or not s['blocks']:
            raise ValueError(f'Calendário ou patamares inválidos no estágio {sid}.')
        ids, horas = set(), []
        for b in s['blocks']:
            bid = _inteiro(b['id'], 'block_id')
            duracao = b['hours']
            if bid in ids or isinstance(duracao, bool) or not isinstance(duracao, (int, float)) or not np.isfinite(duracao) or duracao <= 0:
                raise ValueError(f'Patamar duplicado ou duração inválida no estágio {sid}: {b}')
            ids.add(bid)
            horas.append(float(duracao))
        total = sum(horas)
        if not np.isfinite(total):
            raise ValueError(f'Duração total não finita no estágio {sid}.')
        for b, horas_bloco in zip(s['blocks'], horas):
            pesos.append(dict(stage_id=sid, block_id=b['id'], peso=horas_bloco/total))
        estagios[sid] = dict(s, horas=total)
    if not usinas or not estagios:
        raise ValueError('Cadastro de usinas ou estágios vazio.')
    planejamento = carregar_planejamento(pasta, usinas, estagios)
    return Deck(pasta, usinas, estagios, pd.DataFrame(pesos), planejamento)


def encontrar_cenarios(pasta: Path | str) -> dict[int, Path]:
    pasta = Path(pasta).resolve()
    if not pasta.is_dir():
        raise ValueError(f'Pasta hydros inexistente: {pasta}')
    encontrados = {}
    for subpasta in pasta.glob('scenario_id=*'):
        match = re.fullmatch(r'scenario_id=(\d+)', subpasta.name)
        if not match or not subpasta.is_dir():
            raise ValueError(f'Pasta de cenário inválida: {subpasta}')
        numero = int(match[1])
        arquivo = subpasta/'data.parquet'
        if numero in encontrados or not arquivo.is_file():
            raise ValueError(f'Cenário duplicado ou data.parquet ausente: {subpasta}')
        encontrados[numero] = arquivo
    if not encontrados:
        raise ValueError('Selecione hydros, contendo scenario_id=.../data.parquet.')
    return dict(sorted(encontrados.items()))


def validar_selecao(deck: Deck, usina: int, montantes: list[int]) -> None:
    if usina not in deck.usinas:
        raise ValueError(f'UHE {usina} ausente no cadastro.')
    if len(set(montantes)) != len(montantes):
        raise ValueError('UHE repetida na seleção de montantes.')
    invalidas = set(montantes) - set(deck.montantes_diretas(usina))
    if invalidas:
        raise ValueError(f'As UHEs {sorted(invalidas)} não são montantes diretas da UHE {usina}. '
                         'Selecione apenas as que deságuam diretamente nela, evitando dupla contagem na cascata.')


def consolidar_cenario(arquivo: Path, numero: int, deck: Deck, usina: int,
                       montantes: list[int]) -> pd.DataFrame:
    """A junção das UHEs usa cenário, estágio e nó; a média usa as horas dos patamares."""
    faltantes = set(COLUNAS) - set(pq.read_schema(arquivo).names)
    if faltantes:
        raise ValueError(f'Cenário {numero}: colunas ausentes: {sorted(faltantes)}')
    # ParquetFile evita que a partição scenario_id=0000 altere o tipo da coluna interna.
    bruto = pq.ParquetFile(arquivo).read(columns=COLUNAS).to_pandas()
    if bruto.empty or bruto['scenario_id'].isna().any() or not bruto['scenario_id'].eq(numero).all():
        raise ValueError(f'Cenário {numero}: arquivo vazio ou scenario_id diferente do nome da pasta.')
    dados = bruto.loc[bruto.hydro_id.isin([usina, *montantes])].copy()
    if dados.empty or dados[CHAVE].isna().any().any():
        raise ValueError(f'Cenário {numero}: seleção vazia ou identificadores nulos.')
    for coluna in CHAVE + ['block_id']:
        valores = dados[coluna].dropna()
        if not pd.api.types.is_numeric_dtype(valores) or not np.isfinite(valores).all() or not (valores % 1 == 0).all():
            raise ValueError(f'Cenário {numero}: identificador inválido em {coluna}.')
    for coluna in [*VAZOES, INCREMENTAL, SLACK]:
        if not pd.api.types.is_numeric_dtype(dados[coluna]) or not np.isfinite(dados[coluna]).all():
            raise ValueError(f'Cenário {numero}: vazão nula ou não finita em {coluna}.')
    if dados.duplicated(CHAVE + ['block_id']).any():
        raise ValueError(f'Cenário {numero}: chave de usina/estágio/nó/patamar duplicada.')
    grade = dados[CHAVE].drop_duplicates()
    alvo = grade.loc[grade.hydro_id.eq(usina), TEMPO]
    if alvo.empty or alvo.duplicated(['scenario_id', 'stage_id']).any():
        raise ValueError(f'Cenário {numero}: a UHE analisada deve ter exatamente um nó por estágio.')
    desconhecidos = set(grade.stage_id) - set(deck.estagios)
    if desconhecidos:
        raise ValueError(f'Cenário {numero}: estágios ausentes no deck: {sorted(desconhecidos)}')
    indice_alvo = pd.MultiIndex.from_frame(alvo)
    for hid in [usina, *montantes]:
        indice = pd.MultiIndex.from_frame(grade.loc[grade.hydro_id.eq(hid), TEMPO])
        if len(indice) != len(indice_alvo) or not indice.difference(indice_alvo).empty or not indice_alvo.difference(indice).empty:
            raise ValueError(f'Cenário {numero}: estágio/nó ausente ou divergente na UHE {hid}.')
    blocos = dados.loc[dados.block_id.notna()].copy()
    if blocos.empty:
        # Versões com apenas uma linha de estágio já trazem a vazão consolidada.
        medias = dados[CHAVE + VAZOES].copy()
        base = dados[CHAVE + [INCREMENTAL, SLACK]].copy()
    else:
        if len(blocos[CHAVE].drop_duplicates()) != len(grade):
            raise ValueError(f'Cenário {numero}: mistura incompleta de linhas de estágio e patamares.')
        pesos = deck.pesos.loc[deck.pesos.stage_id.isin(grade.stage_id)]
        esperado = grade.merge(pesos, on='stage_id', how='left', validate='m:m')
        comparacao = esperado[CHAVE + ['block_id']].merge(
            blocos[CHAVE + ['block_id']], on=CHAVE + ['block_id'], how='outer', indicator=True, validate='1:1')
        if not comparacao['_merge'].eq('both').all():
            raise ValueError(f'Cenário {numero}: patamares ausentes ou inesperados frente a stages.json.')
        blocos = blocos.merge(pesos, on=['stage_id', 'block_id'], how='left', validate='m:1')
        medias = blocos[CHAVE].copy()
        for coluna in VAZOES:
            medias[coluna] = blocos[coluna] * blocos['peso']
        medias = medias.groupby(CHAVE, as_index=False, sort=False)[VAZOES].sum()
        repeticoes = blocos.groupby(CHAVE, sort=False)[INCREMENTAL].nunique()
        if not repeticoes.eq(1).all():
            raise ValueError(f'Cenário {numero}: vazão incremental diverge entre patamares.')
        base = blocos.loc[blocos.block_id.eq(0), CHAVE + [INCREMENTAL, SLACK]].copy()
        if len(base) != len(grade):
            raise ValueError(f'Cenário {numero}: block_id=0 ausente para a vazão incremental e o slack.')
    resultado = base.loc[base.hydro_id.eq(usina)].merge(
        medias.loc[medias.hydro_id.eq(usina)], on=CHAVE, validate='1:1')
    adicionais = _consolidar_campos_adicionais(dados, usina, deck)
    resultado = resultado.merge(adicionais, on=CHAVE, validate='1:1')
    resultado['outflow_m3s'] = resultado['turbined_m3s'] + resultado['spillage_m3s']
    resultado['agua_montante_turbinada_m3s'] = 0.0
    resultado['agua_montante_vertida_m3s'] = 0.0
    for hid in sorted(montantes):
        contribuicao = medias.loc[medias.hydro_id.eq(hid), TEMPO + VAZOES].rename(
            columns={c: f'origem_{c}' for c in VAZOES})
        resultado = resultado.merge(contribuicao, on=TEMPO, how='left', validate='1:1')
        resultado['agua_montante_turbinada_m3s'] += resultado['origem_turbined_m3s']
        resultado['agua_montante_vertida_m3s'] += resultado['origem_spillage_m3s']
        resultado[f'agua_montante_uhe_{hid}_m3s'] = resultado['origem_turbined_m3s'] + resultado['origem_spillage_m3s']
        resultado = resultado.drop(columns=['origem_turbined_m3s', 'origem_spillage_m3s'])
    resultado['agua_de_montante_m3s'] = resultado['agua_montante_turbinada_m3s'] + resultado['agua_montante_vertida_m3s']
    resultado['nome_usina'] = deck.usinas[usina]['name']
    resultado['data_inicio'] = resultado.stage_id.map(lambda sid: date.fromisoformat(deck.estagios[sid]['start_date']))
    resultado['data_fim'] = resultado.stage_id.map(lambda sid: date.fromisoformat(deck.estagios[sid]['end_date']))
    resultado = resultado.merge(deck.planejamento, on=['hydro_id', 'stage_id'], how='left', validate='m:1')
    resultado['variacao_armazenamento_hm3'] = resultado.storage_final_hm3 - resultado.storage_initial_hm3
    resultado['deficit_meta_enchimento_hm3'] = (resultado.filling_target_hm3 - resultado.storage_final_hm3).clip(lower=0)
    return resultado.sort_values(['stage_id', 'scenario_id']).reset_index(drop=True)


def informar(texto: str) -> None:
    print(texto, flush=True)


def consolidar(pasta_hydros: Path | str, pasta_deck: Path | str, usina: int,
               montantes: list[int], arquivo_saida: Path | str, *,
               cenarios_esperados: int | None = None, sobrescrever: bool = False,
               progresso: Callable[[str], None] = informar) -> Path:
    deck = carregar_deck(pasta_deck)
    validar_selecao(deck, usina, montantes)
    cenarios = encontrar_cenarios(pasta_hydros)
    if cenarios_esperados is not None and len(cenarios) != cenarios_esperados:
        raise ValueError(f'Esperados {cenarios_esperados} cenários; encontrados {len(cenarios)}.')
    saida = Path(arquivo_saida).resolve()
    if saida.suffix.lower() != '.parquet':
        raise ValueError('O arquivo de saída deve ter extensão .parquet.')
    if Path(pasta_hydros).resolve() == saida.parent or Path(pasta_hydros).resolve() in saida.parents:
        raise ValueError('Salve o consolidado fora da pasta hydros de origem.')
    if saida.exists() and not sobrescrever:
        raise ValueError(f'A saída já existe: {saida}. Use outro nome ou --sobrescrever.')
    partes, estagios_referencia = [], None
    for posicao, (numero, arquivo) in enumerate(cenarios.items(), 1):
        if posicao == 1 or posicao % 50 == 0 or posicao == len(cenarios):
            progresso(f'Cenário {numero:04d}: {posicao}/{len(cenarios)}')
        try:
            parte = consolidar_cenario(arquivo, numero, deck, usina, montantes)
        except Exception as erro:
            raise ValueError(f'Falha em {arquivo}: {erro}') from erro
        estagios = set(parte.stage_id)
        if estagios_referencia is None:
            estagios_referencia = estagios
            if estagios != set(deck.estagios):
                raise ValueError('Os estágios da UHE não coincidem com stages.json. Confira se é o deck da mesma execução.')
        elif estagios != estagios_referencia:
            raise ValueError(f'Cenário {numero}: conjunto de estágios difere do primeiro cenário.')
        partes.append(parte)
    resultado = pd.concat(partes, ignore_index=True).sort_values(['stage_id', 'scenario_id']).reset_index(drop=True)
    if resultado.duplicated(['stage_id', 'scenario_id']).any() or not resultado.groupby('stage_id').size().eq(len(cenarios)).all():
        raise ValueError('Quantidade de cenários por estágio inconsistente.')
    metadados = dict(
        versao=3, pasta_hydros=str(Path(pasta_hydros).resolve()), pasta_deck=str(deck.pasta),
        hydro_id=usina, nome_usina=deck.usinas[usina]['name'],
        montantes_selecionadas=[dict(hydro_id=i, nome=deck.usinas[i]['name']) for i in sorted(montantes)],
        montantes_diretas=deck.montantes_diretas(usina),
        selecao_completa=set(montantes) == set(deck.montantes_diretas(usina)),
        numero_cenarios=len(cenarios), scenario_ids=list(cenarios), numero_estagios=len(estagios_referencia),
        linhas=len(resultado), unidade='mista; consultar unidades_por_coluna',
        unidades_por_coluna={c: ('h' if c == 'horas_estagio' else 'hm3' if c.endswith('_hm3')
                                else 'MW' if c.endswith('_mw') else 'm3/s')
                            for c in resultado if c.endswith(('_m3s', '_hm3', '_mw')) or c == 'horas_estagio'},
        tratamento_campos_adicionais={
            'escopo': 'Somente a usina analisada; não soma valores das montantes.',
            'media_ponderada_pelas_horas': TAXAS_ADICIONAIS,
            'volume_unico_por_estagio': VOLUMES_ADICIONAIS,
            'sem_patamares': 'Copia os valores da linha de estágio.',
        },
        indices='IDs originais, sem renumerar',
        planejamento={
            'fonte_meta': FONTE_META,
            'hydro_bounds_presente': (deck.pasta/ARQUIVO_LIMITES).is_file(),
            'overrides': 'Por UHE, estágio e coluna; nulos/ausentes usam o padrão, sem propagar o mês anterior.',
            'retirada': 'Programada, com sinal; não é a retirada realizada nem inclui roteamento de pré-enchimento.',
            'volume_referencia': 'filling_min_rate_m3s * horas_estagio * 0.0036; não é a meta absoluta.',
            'fora_do_enchimento': 'volume_referencia_enchimento_hm3, filling_target_hm3 e deficit_meta_enchimento_hm3 são nulos.',
            'mes_referencia': 'Ano-mês da data inicial do estágio; durações vêm dos patamares, não do mês civil.',
            'horas_estagio_unidade': 'h',
        },
        formula='sum_u sum_b [(turbined_m3s + spillage_m3s) * hours_b / sum_b(hours_b)]',
        escopo='Soma das montantes diretas selecionadas no mesmo cenário, estágio e nó. Sem adicionar slack, desvios, perdas ou tempo de viagem.',
        sha256={n: hashlib.sha256((deck.pasta/n).read_bytes()).hexdigest()
                for n in ['stages.json', 'system/hydros.json', ARQUIVO_LIMITES] if (deck.pasta/n).is_file()},
    )
    for c in CHAVE:
        resultado[c] = resultado[c].astype('int64')
    tabela = pa.Table.from_pandas(resultado, preserve_index=False)
    metadata = dict(tabela.schema.metadata or {})
    metadata[b'extrator_hydros'] = json.dumps(metadados, ensure_ascii=False).encode('utf-8')
    tabela = tabela.replace_schema_metadata(metadata)
    saida.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=saida.parent, suffix='.parquet.tmp', delete=False) as f:
        temporario = Path(f.name)
    try:
        pq.write_table(tabela, temporario, compression='zstd', row_group_size=len(cenarios))
        if saida.exists() and not sobrescrever:
            raise ValueError('A saída passou a existir durante o processamento; escolha outro nome.')
        os.replace(temporario, saida)
    finally:
        temporario.unlink(missing_ok=True)
    progresso(f'Concluído: {len(resultado):,} linhas; {len(cenarios)} cenários por estágio.\n{saida}')
    return saida
