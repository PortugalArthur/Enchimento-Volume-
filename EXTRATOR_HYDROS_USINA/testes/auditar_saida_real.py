"""Confere o consolidado por uma conta independente com numpy.average."""
import argparse
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


def auditar(saida):
    saida=Path(saida)
    tabela=pq.ParquetFile(saida).read()
    df=tabela.to_pandas()
    meta=json.loads(tabela.schema.metadata[b'extrator_hydros'])
    cenarios=meta['scenario_ids']
    estagios=sorted(df.stage_id.unique().tolist())
    assert len(df)==len(cenarios)*len(estagios)
    assert not df.duplicated(['scenario_id','stage_id']).any()
    assert df.groupby('stage_id').size().eq(len(cenarios)).all()
    assert sorted(df.scenario_id.unique().tolist())==cenarios
    assert df.hydro_id.eq(meta['hydro_id']).all()
    deck=Path(meta['pasta_deck'])
    stages=json.loads((deck/'stages.json').read_text(encoding='utf-8-sig'))
    cadastro={s['id']:s for s in stages['stages']}
    amostras=[]
    for c in sorted({cenarios[0],cenarios[len(cenarios)//2],cenarios[-1]}):
        candidatos=list(Path(meta['pasta_hydros']).glob(f'scenario_id=*/data.parquet'))
        arquivo=next(p for p in candidatos if int(p.parent.name.split('=')[1])==c)
        bruto=pq.ParquetFile(arquivo).read(columns=['scenario_id','stage_id','node_id','hydro_id','block_id','turbined_m3s','spillage_m3s']).to_pandas()
        for s in sorted({estagios[0],estagios[len(estagios)//2],estagios[-1]}):
            linha=df[(df.scenario_id==c)&(df.stage_id==s)].iloc[0]
            horas={b['id']:b['hours'] for b in cadastro[s]['blocks']}
            total=0
            for u in meta['montantes_selecionadas']:
                hid=u['hydro_id']
                orig=bruto[(bruto.scenario_id==c)&(bruto.stage_id==s)&(bruto.node_id==linha.node_id)&(bruto.hydro_id==hid)]
                blocos=orig[orig.block_id.notna()]
                if blocos.empty:
                    assert len(orig)==1
                    valor=float(orig.iloc[0].turbined_m3s+orig.iloc[0].spillage_m3s)
                else:
                    assert set(blocos.block_id)==set(horas)
                    valor=float(np.average(blocos.turbined_m3s+blocos.spillage_m3s,
                                           weights=[horas[b] for b in blocos.block_id]))
                np.testing.assert_allclose(linha[f'agua_montante_uhe_{hid}_m3s'],valor,rtol=1e-12,atol=1e-9)
                total+=valor
            np.testing.assert_allclose(linha.agua_de_montante_m3s,total,rtol=1e-12,atol=1e-9)
            amostras.append(dict(scenario_id=c,stage_id=s,node_id=int(linha.node_id),agua_de_montante_m3s=total))
    return dict(arquivo=str(saida.resolve()),usina=meta['nome_usina'],linhas=len(df),estagios=len(estagios),
                cenarios_por_estagio=len(cenarios),chaves_unicas=True,contas_independentes=len(amostras),
                amostras=amostras)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('saida',type=Path)
    parser.add_argument('--relatorio',type=Path)
    args=parser.parse_args()
    resultado=auditar(args.saida)
    texto=json.dumps(resultado,ensure_ascii=False,indent=2)
    print(texto)
    if args.relatorio:
        args.relatorio.write_text(texto+'\n',encoding='utf-8')
