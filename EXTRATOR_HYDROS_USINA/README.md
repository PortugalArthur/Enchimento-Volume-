# Extrator HYDROS por usina

Execute **EXTRAIR_HYDROS_USINA.bat** com duplo clique. O programa prepara as bibliotecas ausentes na primeira execução, seguindo o padrão dos outros programas da pasta Vazoes.

No Windows, o lançador procura Python 3.10 ou mais recente com Tkinter pelo launcher `py`, pelo PATH, pelo registro e pelas pastas usuais de instalação. Para indicar uma instalação personalizada, execute no Prompt de Comando:

```bat
set "EXTRATOR_PYTHON=C:\caminho\Python312\python.exe"
EXTRAIR_HYDROS_USINA.bat
```

Se nenhuma instalação compatível for encontrada, instale o Python com os componentes launcher e Tcl/Tk habilitados.

## Seleção e saída

### Visualizar o Parquet gerado

Abra **LER_PARQUET_HYDROS.bat** com duplo clique e clique em **Abrir Parquet…**. O leitor instala as bibliotecas ausentes na primeira execução e abre os consolidados sem precisar do deck ou dos Parquets brutos.

- **Evolução por estágio:** escolha a grandeza e consulte a média, mediana e faixa P10–P90 entre cenários. Selecione um cenário para ver sua trajetória individual. O eixo usa os IDs originais dos estágios; as datas estão na tabela.
- **Distribuição:** histograma de todas as observações do filtro. Para comparar cenários em um mesmo período, escolha um estágio.
- **Tabela:** todas as colunas, com páginas de 200 linhas e rolagem horizontal.
- **Metadados e origem:** usina, montantes, seleção parcial, fórmula e informações da geração.
- **Exportar filtro para CSV…:** exporta todas as linhas e colunas filtradas, independentemente da página atual, com separador `;`, vírgula decimal e codificação UTF-8 para Excel. Escolha um nome novo; arquivos existentes são preservados.

As vazões são apresentadas em m³/s, os volumes em hm³ e o slack de geração em MW. A unidade da grandeza selecionada aparece no seletor, no resumo e nos eixos dos gráficos. P10 e P90 são percentis empíricos, não probabilidades de excedência. Na barra abaixo dos gráficos é possível ampliar, mover e salvar imagens. O arquivo é carregado na memória; para arquivos maiores que a memória disponível, gere consolidados menores. Consolidados antigos continuam abrindo, com as colunas que já possuem.

Também é possível abrir diretamente pelo terminal, na pasta do programa:

```powershell
python -m aplicacao.ler_parquet outputs/validacao_furnas_v20_2000_cenarios.parquet
```

### Gerar o gráfico HTML interativo

Abra **GERAR_GRAFICO_HTML.bat** ou use **Gerar HTML interativo...** no leitor. Escolha o consolidado atualizado e um nome novo para o HTML. O arquivo abre no navegador e funciona sem internet, inclusive em outro computador: dados de todos os cenários e a biblioteca de gráficos ficam incluídos no próprio HTML. Use uma versão atual do Edge, Chrome ou Firefox (o navegador precisa suportar `DecompressionStream`).

O seletor permite escolher **um único cenário por vez** entre os IDs presentes no Parquet. As dez séries aparecem **no mesmo gráfico**, com todos os estágios do cenário. Cada série tem uma caixa para ocultar/exibir e um seletor de cor; a legenda também oculta/exibe séries. As cores e visibilidades são mantidas ao trocar de cenário durante a sessão. Há zoom e exportação de imagem na barra do gráfico.

Todas as curvas estão em **hm³**. Vazões médias já ponderadas pelos patamares são multiplicadas por `horas_estagio × 0,0036`, sem ponderação duplicada:

1. **Afluente:** `(agua_montante_turbinada_m3s + agua_montante_vertida_m3s + incremental_inflow_m3s + inflow_nonnegativity_slack_m3s) × horas_estagio × 0,0036`.
2. **Turbinada pela usina:** `turbined_m3s × horas_estagio × 0,0036`.
3. **Vertida pela usina:** `spillage_m3s × horas_estagio × 0,0036`.
4. **Meta de enchimento:** `filling_target_hm3`, sem conversão; é armazenamento absoluto, não fluxo do período.
5. **Retirada programada:** `water_withdrawal_m3s × horas_estagio × 0,0036`, preservando o sinal.
6. **Folga da meta de enchimento:** `filling_target_violation_hm3`, sem conversão.
7. **Folga de retirada para menos:** `water_withdrawal_violation_neg_m3s × horas_estagio × 0,0036`, preservando o valor original.
8. **Evaporação efetiva:** `evaporation_m3s × horas_estagio × 0,0036`, preservando o sinal.
9. **Variação do armazenamento:** `storage_final_hm3 − storage_initial_hm3`, sem nova conversão. Valores positivos indicam aumento do armazenamento; negativos indicam redução.
10. **Folga de retirada para mais:** `water_withdrawal_violation_pos_m3s × horas_estagio × 0,0036`, preservando o valor original. Na retirada efetiva, a folga para menos é subtraída e a folga para mais é somada à retirada programada; as curvas mostram os valores das folgas sem inversão de sinal.

A meta fora do enchimento é nula e a linha fica interrompida. A afluente usa as montantes selecionadas na extração; o HTML avisa quando a seleção é parcial. A definição acima não inclui desvios, bombeamento nem afluências encaminhadas de locais em pré-enchimento: não é sozinha o fechamento completo do balanço. O HTML inclui todos os cenários e estágios, mesmo se o leitor estiver filtrado; o cenário selecionado no leitor será apenas a seleção inicial.

Para usar pelo terminal:

```powershell
python -m aplicacao.gerar_html outputs/resultado.parquet --saida outputs/grafico.html --cenario 4
```

Use `--nao-abrir` para gerar sem abrir o navegador. Consolidados antigos sem as novas colunas ou sem `horas_estagio` precisam ser gerados novamente; o programa não adivinha horas nem inventa dados ausentes. Arquivos existentes não são substituídos. A instalação automática inclui `plotly>=5.18`.

### Gerar um consolidado

1. Escolha a pasta `hydros`, contendo `scenario_id=.../data.parquet`.
2. Escolha a raiz do **deck de entrada da mesma execução**, preservando `stages.json`, `system/hydros.json` e, quando existente no estudo, `constraints/hydro_bounds.parquet`. O extrator lê os três automaticamente, sem novos seletores.
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

### Campos adicionais da usina analisada

As novas extrações incluem os 15 campos abaixo, com os nomes originais. Eles descrevem somente a usina analisada; não são somados aos valores das montantes e não alteram o cálculo de `agua_de_montante_m3s`.

| Campo | Unidade | Tratamento por estágio |
| --- | --- | --- |
| `evaporation_m3s` | m³/s | Média ponderada pelas horas dos patamares |
| `diverted_inflow_m3s` | m³/s | Média ponderada pelas horas dos patamares |
| `diverted_outflow_m3s` | m³/s | Média ponderada pelas horas dos patamares |
| `storage_initial_hm3` | hm³ | Volume inicial do estágio, preservado uma única vez |
| `storage_final_hm3` | hm³ | Volume final do estágio, preservado uma única vez |
| `turbined_slack_m3s` | m³/s | Média ponderada pelas horas dos patamares |
| `outflow_slack_below_m3s` | m³/s | Média ponderada pelas horas dos patamares |
| `outflow_slack_above_m3s` | m³/s | Média ponderada pelas horas dos patamares |
| `generation_slack_mw` | MW | Média ponderada pelas horas dos patamares |
| `storage_violation_below_hm3` | hm³ | Valor do estágio, preservado uma única vez |
| `filling_target_violation_hm3` | hm³ | Valor do estágio, preservado uma única vez |
| `evaporation_violation_pos_m3s` | m³/s | Média ponderada pelas horas dos patamares |
| `evaporation_violation_neg_m3s` | m³/s | Média ponderada pelas horas dos patamares |
| `water_withdrawal_violation_pos_m3s` | m³/s | Média ponderada pelas horas dos patamares |
| `water_withdrawal_violation_neg_m3s` | m³/s | Média ponderada pelas horas dos patamares |

Os quatro campos em hm³ devem ser iguais entre os patamares de um mesmo cenário, estágio e nó. O extrator verifica isso antes de copiar o valor do patamar 0; não soma nem faz média dos volumes. Para taxas repetidas entre patamares, a média mantém o mesmo valor, dentro da precisão numérica. Para arquivos contendo apenas linhas de estágio (`block_id` nulo), todos os 15 campos são copiados diretamente.

As 15 colunas são obrigatórias nas entradas das novas extrações. Campos ausentes ou valores não numéricos/não finitos da usina analisada interrompem a geração sem substituir a saída anterior; o extrator não preenche dados ausentes com zero. O tratamento desses campos foi introduzido nos metadados `extrator_hydros` versão 2 e permanece na versão 3, com `unidades_por_coluna` e `tratamento_campos_adicionais`. `unidade` indica unidades mistas; consulte o mapa por coluna.

**Para obter esses campos em um consolidado já gerado, execute novamente o extrator a partir dos Parquets originais.** O leitor não consegue recuperar colunas descartadas de uma saída antiga. O exemplo histórico de FURNAS incluído no repositório permanece sem esses novos campos.

### Enchimento, metas e retirada programada

As novas extrações também cruzam o deck com as observações da usina por `hydro_id` e `stage_id`. Os parâmetros são repetidos em cada cenário, sem somar patamares nem alterar o número de linhas. No leitor, as grandezas numéricas ficam disponíveis para gráficos e exportação; período, mês e IDs aparecem na tabela.

| Coluna | Unidade | Conteúdo |
| --- | --- | --- |
| `em_enchimento` | booleano | `filling.start_stage_id <= stage_id < entry_stage_id`, quando há configuração `filling` |
| `filling_start_stage_id` | ID | Início do enchimento; nulo quando não há `filling` |
| `entry_stage_id` | ID | Entrada em operação do cadastro, quando informada |
| `mes_referencia` | AAAA-MM | Ano-mês da **data inicial** do estágio |
| `horas_estagio` | h | Soma das horas dos patamares de `stages.json` |
| `min_storage_hm3` | hm³ | Volume mínimo operacional resolvido para aquele estágio |
| `filling_min_rate_m3s` | m³/s | Taxa mínima resolvida: padrão do cadastro e substituição por estágio, quando houver |
| `volume_referencia_enchimento_hm3` | hm³ | Taxa mínima × horas do estágio × 0,0036, durante o enchimento |
| `filling_target_hm3` | hm³ | Meta absoluta de armazenamento calculada conforme a trajetória do modelo |
| `water_withdrawal_m3s` | m³/s | Retirada **programada**, com sinal: positiva retira água; negativa representa aporte/retorno |
| `water_withdrawal_hm3` | hm³ | Retirada programada × horas do estágio × 0,0036 |
| `variacao_armazenamento_hm3` | hm³ | `storage_final_hm3 - storage_initial_hm3`, em cada cenário |
| `deficit_meta_enchimento_hm3` | hm³ | `max(0, filling_target_hm3 - storage_final_hm3)`, durante o enchimento |

**Volume de referência não é a meta absoluta.** A trajetória reproduz `build_filling_v_target` do Novo Modelo v0.20.0: o último estágio de enchimento (`entry_stage_id - 1`) recebe o volume mínimo resolvido daquele estágio. Para os anteriores, o cálculo anda para trás subtraindo os volumes de referência dos estágios posteriores. Cada meta é limitada superiormente pelo volume mínimo resolvido do seu estágio, sem alimentar esse limite de volta no acumulador. Metas negativas são preservadas, como na implementação oficial; não são truncadas em zero. Se há enchimento dentro do horizonte e falta o estágio de ancoragem, a extração é interrompida, sem inventar uma meta.

`constraints/hydro_bounds.parquet` é esparso: `min_storage_hm3`, `filling_min_rate_m3s` e `water_withdrawal_m3s` não nulos substituem os padrões somente da mesma UHE e estágio. Valores nulos ou ausentes não propagam valores do mês anterior. O padrão do volume mínimo vem de `reservoir.min_storage_hm3`; a taxa vem de `filling.filling_min_rate_m3s` (zero quando omitida); a retirada padrão é zero. Um zero explícito é uma substituição válida. Esses três parâmetros só podem aparecer em linhas de estágio (`block_id` ausente ou nulo); referências desconhecidas, valores inválidos e duplicatas da mesma coluna são rejeitados. Linhas distintas que configuram colunas diferentes são aceitas. Quando o Parquet de limites não existe, aplicam-se os padrões e sua ausência fica registrada nos metadados.

Fora do enchimento, `volume_referencia_enchimento_hm3`, `filling_target_hm3` e `deficit_meta_enchimento_hm3` são **nulos**, não zero. O leitor mostra `N/A` na tabela, ignora esses valores em estatísticas/histogramas e os exporta como células vazias no CSV. Consolidados antigos continuam abrindo. Para estágios semanais ou de outra resolução, os volumes continuam sendo **por estágio**; não há agrupamento mensal nem uso automático de dias do mês civil.

`filling_target_violation_hm3` continua sendo a folga original da simulação. O déficit é uma comparação com a meta, não uma declaração de causa nem água adicionada ao reservatório. `water_withdrawal_m3s` e `water_withdrawal_hm3` não são retirada realizada: não descontam slacks nem reproduzem o roteamento de demandas de usinas em pré-enchimento. A análise do balanço e das causas fica para a etapa seguinte.

Os metadados `extrator_hydros` passam à versão **3**, mantendo o tratamento dos 15 campos anteriores e acrescentando fonte da fórmula, regras de planejamento, unidades e hash SHA-256 de `hydro_bounds.parquet` quando presente. Para reconstituir os seus dados reais é necessário executar novamente a extração com o deck e os Parquets brutos da mesma execução.

Fontes oficiais:

- [Schema do cadastro hidráulico](https://github.com/ons-ccee-epe/novomodelo/blob/v0.20.0/schemas/hydros.schema.json).
- [Período de enchimento](https://github.com/ons-ccee-epe/novomodelo/blob/v0.20.0/crates/novomodelo-core/src/commissioning.rs).
- [Resolução dos limites por estágio](https://github.com/ons-ccee-epe/novomodelo/blob/v0.20.0/crates/novomodelo-io/src/resolution/bounds.rs).
- [Trajetória de metas e testes de referência](https://github.com/ons-ccee-epe/novomodelo/blob/v0.20.0/crates/novomodelo-sddp/src/setup/lp_build_inputs.rs).

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
