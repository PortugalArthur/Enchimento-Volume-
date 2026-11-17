# Extrator HYDROS por usina

Execute **EXTRAIR_HYDROS_USINA.bat** com duplo clique. O programa prepara as bibliotecas ausentes na primeira execução, seguindo o padrão dos outros programas da pasta Vazoes.

No Windows, o lançador procura Python 3.10 ou mais recente com Tkinter pelo launcher `py`, pelo PATH, pelo registro e pelas pastas usuais de instalação. Para indicar uma instalação personalizada, execute no Prompt de Comando:

```bat
set "EXTRATOR_PYTHON=C:\caminho\Python312\python.exe"
EXTRAIR_HYDROS_USINA.bat
```

Se nenhuma instalação compatível for encontrada, instale o Python com os componentes launcher e Tcl/Tk habilitados.

## Seleção e saída

1. Escolha a pasta `hydros`, contendo `scenario_id=.../data.parquet`.
2. Escolha a raiz do **deck de entrada da mesma execução**. São necessários `stages.json` e `system/hydros.json`.
3. Busque a usina pelo nome ou ID e selecione-a.
4. Confira as montantes diretas, inicialmente todas selecionadas. Use Ctrl+clique para alterar.
5. Clique em **Gerar Parquet da usina** e escolha o destino. A pasta padrão é `outputs`.

A janela permanece disponível durante o processamento e informa o progresso. Há uma linha por cenário e estágio, com o nó original preservado. Com 2.000 cenários e 72 estágios, são 144.000 linhas. A quantidade é descoberta nos dados, sem fabricar cenários ausentes. No modo CLI é possível exigir exatamente 2.000 usando `--cenarios-esperados 2000`.

Os IDs não são renumerados: o cenário 0000 permanece `scenario_id=0`. O arquivo fica ordenado por estágio e cenário; cada grupo de linhas do Parquet corresponde a um estágio.

## Como a água de montante é calculada

Para um mesmo cenário, estágio e nó:

```text
agua_de_montante_m3s = soma, sobre as UHEs selecionadas, de:
    soma_patamares((turbined_m3s + spillage_m3s) * horas_patamar)
    / soma_patamares(horas_patamar)
```

As horas vêm dos blocos do estágio em `stages.json`. Não se somam diretamente vazões de patamares, pois os valores são taxas em m³/s. A média deve ser ponderada pelas durações. Por exemplo, 100 m³/s durante 100 horas e 200 m³/s durante 300 horas resultam em **175 m³/s** no estágio. Duas montantes com médias de 175 e 25 m³/s resultam em **200 m³/s de água de montante**.

Somente as **montantes diretas**, identificadas por `downstream_id == hydro_id da usina analisada`, podem ser selecionadas. Na cascata `A → B → C`, a contribuição para C vem de B. Somar A e B contaria novamente a água que passou pelas duas. Em uma confluência, somam-se as últimas usinas de cada ramo que deságua diretamente na usina analisada.

Se houver linhas-resumo com `block_id` nulo juntamente com patamares, usam-se os patamares para a ponderação; as linhas-resumo não entram novamente na soma. Se a versão contiver somente linhas de estágio, usam-se essas vazões já consolidadas.

Não se adiciona o slack à água de montante: as vazões turbinadas e vertidas registradas já são as liberações simuladas. A coluna representa essas liberações das usinas selecionadas no mesmo estágio; não reconstrói o balanço hidráulico completo. Desvios, bombeamentos, perdas no percurso e tempos de viagem exigiriam regras adicionais. Quando a seleção omite alguma montante direta, a contribuição é parcial e isso fica registrado nos metadados. Em usina de cabeceira, a contribuição é zero.

## Colunas

As seis primeiras seguem a base do consolidado existente:

| Coluna | Conteúdo |
| --- | --- |
| `scenario_id`, `stage_id`, `node_id`, `hydro_id` | IDs originais da usina analisada |
| `incremental_inflow_m3s` | Vazão incremental local da usina |
| `inflow_nonnegativity_slack_m3s` | Slack local copiado do patamar 0, conforme o gerador existente |
| `turbined_m3s`, `spillage_m3s`, `outflow_m3s` | Médias do estágio da própria usina; outflow = turbinada + vertida |
| `agua_montante_turbinada_m3s` | Soma das médias turbinadas das montantes selecionadas |
| `agua_montante_vertida_m3s` | Soma das médias vertidas das montantes selecionadas |
| `agua_montante_uhe_ID_m3s` | Contribuição total individual de cada montante selecionada |
| `agua_de_montante_m3s` | Soma das contribuições das montantes selecionadas, em m³/s |
| `nome_usina`, `data_inicio`, `data_fim` | Nome e calendário do estágio, com fim exclusivo |

O arquivo é específico para a análise de uma usina e não carrega os parâmetros PAR do avaliador estatístico. A seleção, fórmula, cenários, caminhos e hashes dos cadastros ficam incorporados nos metadados Parquet na chave `extrator_hydros`.

A documentação oficial descreve `outflow_m3s` como turbinada + vertida e informa que `inflow_m3s` é a vazão incremental local, sem contribuição das montantes: [Simulation Output](https://docs.cobre-rs.dev/v0.17/reference/output/simulation/). As durações dos patamares são declaradas em horas: [schema de stages.json](https://raw.githubusercontent.com/ons-ccee-epe/novomodelo/refs/heads/main/schemas/stages.schema.json).

## Verificações

A associação usa cenário + estágio + nó, sem depender da ordem física das linhas. O programa rejeita cenário interno diferente da pasta, chaves duplicadas, usina/estágio/nó ausente, patamar faltante ou inesperado, vazão não finita e durações inválidas. Exige uma observação por cenário e estágio da usina analisada e os mesmos estágios do deck. Mantém a saída anterior em caso de falha e publica o novo arquivo somente ao concluir as validações.

Não se consegue provar apenas pelos Parquets que dois decks com os mesmos IDs e calendários são a mesma execução; por isso é necessário selecionar o deck correspondente.

## Linha de comando

Na pasta deste programa:

```powershell
python -m aplicacao.executar --hydros "CAMINHO\hydros" --deck "CAMINHO\deck" --usina 3 --montantes 2 --saida "outputs\furnas.parquet" --cenarios-esperados 2000
```

Omitir `--montantes` seleciona todas as montantes diretas. Usar `--montantes` sem IDs seleciona nenhuma. Para substituir uma saída existente no modo CLI, informe `--sobrescrever`.

## Validação realizada

- 19 testes automatizados com conta ponderada conhecida, dois ramos de montante, IDs não contíguos, linhas embaralhadas, dados incompletos e conservação da saída anterior.
- Verificação da interface: busca por FURNAS, pré-seleção de FUNIL-GRANDE e tratamento de CAMARGOS como cabeceira.
- Execução completa em `V_0_20/Saidas_COBRE/output/simulation/hydros`, com o deck `DECK_COBE_V20`, para FURNAS (ID 3), recebendo FUNIL-GRANDE (ID 2): 144.000 linhas, 72 estágios e 2.000 cenários por estágio.
- Auditoria independente da estrutura completa e de nove contas amostrais com `numpy.average`, em cenários 0, 1000 e 1999 e estágios 0, 36 e 71. Evidência em `documentacao/VALIDACAO_REAL.json`; exemplo em `outputs/validacao_furnas_v20_2000_cenarios.parquet`.

```powershell
python -m unittest discover -s testes -v
python -m testes.auditar_saida_real outputs\validacao_furnas_v20_2000_cenarios.parquet
```
