"""Visualizador desktop dos Parquets consolidados por usina."""
import argparse
import json
from pathlib import Path
import queue
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.font import nametofont

from infraestrutura.preparar_ambiente import garantir_dependencias

garantir_dependencias({'numpy': 'numpy>=1.24', 'pandas': 'pandas>=2.0',
                      'pyarrow': 'pyarrow>=14', 'matplotlib': 'matplotlib>=3.8', 'plotly': 'plotly>=5.18'})

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
import pandas as pd
from dados.leitor import Consolidado, rotulo, unidade
from dados.grafico_html import gerar_html


TODOS = 'Todos'
TAMANHO_PAGINA = 200


class Leitor(ttk.Frame):
    def __init__(self, janela):
        super().__init__(janela, padding=12)
        self.pack(fill='both', expand=True)
        janela.title('Leitor HYDROS — Parquets por usina')
        janela.geometry('1180x800')
        janela.minsize(900, 650)
        nametofont('TkDefaultFont').configure(size=10)
        estilo = ttk.Style(self)
        estilo.configure('Treeview', rowheight=26)
        estilo.configure('TNotebook.Tab', padding=(12, 6))
        estilo.configure('TButton', padding=(8, 5))
        self.base = None
        self.pagina = 0
        self.fila = queue.Queue()
        self.fila_html = queue.Queue()
        topo = ttk.Frame(self)
        topo.pack(fill='x')
        self.abrir_botao = ttk.Button(topo, text='Abrir Parquet...', command=self.escolher)
        self.abrir_botao.pack(side='left')
        self.exportar_botao = ttk.Button(topo, text='Exportar filtro para CSV...', command=self.exportar, state='disabled')
        self.exportar_botao.pack(side='left', padx=8)
        self.html_botao = ttk.Button(topo, text='Gerar HTML interativo...', command=self.exportar_html, state='disabled')
        self.html_botao.pack(side='left')
        self.arquivo = tk.StringVar(value='Abra um Parquet gerado pelo extrator para começar.')
        ttk.Label(self, textvariable=self.arquivo, wraplength=1080).pack(anchor='w', pady=8)
        self.informacoes = tk.StringVar()
        ttk.Label(self, textvariable=self.informacoes, wraplength=1080).pack(anchor='w')

        filtros = ttk.Frame(self)
        filtros.pack(fill='x', pady=12)
        self.cenario = self.combo(filtros, 'Cenário', 14)
        self.estagio = self.combo(filtros, 'Estágio', 14)
        self.metrica = self.combo(filtros, 'Grandeza e unidade', 48)
        self.contagem = tk.StringVar()
        ttk.Label(self, textvariable=self.contagem).pack(anchor='w', pady=(0, 8))

        abas = ttk.Notebook(self)
        abas.pack(fill='both', expand=True)
        self.figuras = []
        for titulo in ['Evolução por estágio', 'Distribuição']:
            quadro = ttk.Frame(abas)
            abas.add(quadro, text=titulo)
            figura = Figure(figsize=(9, 4), dpi=100, layout='constrained')
            eixo = figura.add_subplot(111)
            canvas = FigureCanvasTkAgg(figura, master=quadro)
            NavigationToolbar2Tk(canvas, quadro).pack(side='bottom', fill='x')
            canvas.get_tk_widget().pack(fill='both', expand=True)
            self.figuras.append((eixo, canvas))
        tabela = ttk.Frame(abas)
        abas.add(tabela, text='Tabela')
        tabela.rowconfigure(0, weight=1)
        tabela.columnconfigure(0, weight=1)
        self.tabela = ttk.Treeview(tabela, show='headings')
        self.tabela.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(tabela, orient='vertical', command=self.tabela.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(tabela, orient='horizontal', command=self.tabela.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tabela.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        paginas = ttk.Frame(tabela)
        paginas.grid(row=2, column=0, sticky='ew', pady=6)
        self.anterior = ttk.Button(paginas, text='Anterior', command=lambda: self.mudar_pagina(-1), state='disabled')
        self.anterior.pack(side='left')
        self.proxima = ttk.Button(paginas, text='Próxima', command=lambda: self.mudar_pagina(1), state='disabled')
        self.proxima.pack(side='left', padx=8)
        self.paginacao = tk.StringVar()
        ttk.Label(paginas, textvariable=self.paginacao).pack(side='left')
        meta = ttk.Frame(abas)
        abas.add(meta, text='Metadados e origem')
        self.meta = tk.Text(meta, wrap='word', state='disabled', padx=12, pady=12)
        barra = ttk.Scrollbar(meta, command=self.meta.yview)
        barra.pack(side='right', fill='y')
        self.meta.configure(yscrollcommand=barra.set)
        self.meta.pack(fill='both', expand=True)
        self.status = tk.StringVar(value='Nenhum arquivo aberto.')
        ttk.Label(self, textvariable=self.status).pack(anchor='w', pady=(8, 0))
        self.after(100, self.verificar_fila)

    def combo(self, pai, titulo, largura):
        quadro = ttk.Frame(pai)
        quadro.pack(side='left', padx=(0, 16))
        ttk.Label(quadro, text=titulo).pack(anchor='w')
        combo = ttk.Combobox(quadro, width=largura, state='disabled')
        combo.pack()
        combo.bind('<<ComboboxSelected>>', self.atualizar)
        return combo

    def escolher(self):
        caminho = filedialog.askopenfilename(parent=self, title='Abrir consolidado da usina',
                                             filetypes=[('Parquet', '*.parquet')])
        if caminho:
            self.abrir(caminho)

    def abrir(self, caminho):
        self.abrir_botao.configure(state='disabled')
        self.status.set('Carregando Parquet...')

        def carregar():
            try:
                self.fila.put((Consolidado.abrir(caminho), None))
            except Exception as erro:
                self.fila.put((None, str(erro)))
        threading.Thread(target=carregar, daemon=True).start()

    def verificar_fila(self):
        try:
            base, erro = self.fila.get_nowait()
            self.abrir_botao.configure(state='normal')
            if erro:
                self.status.set('Falha ao abrir. O arquivo anterior foi mantido.')
                messagebox.showerror('Não foi possível abrir o Parquet', erro, parent=self)
            else:
                self.definir_base(base)
        except queue.Empty:
            pass
        try:
            destino, erro = self.fila_html.get_nowait()
            self.html_botao.configure(state='normal')
            if erro:
                messagebox.showerror('Falha ao gerar HTML', erro, parent=self)
                self.status.set('HTML não gerado. Confira o erro informado.')
            else:
                self.status.set(f'HTML gerado: {destino}')
                webbrowser.open(destino.resolve().as_uri())
        except queue.Empty:
            pass
        self.after(100, self.verificar_fila)

    def definir_base(self, base):
        self.base = base
        df = base.dados
        nome = base.metadados.get('nome_usina')
        if not nome:
            nome = str(df.nome_usina.iloc[0]) if 'nome_usina' in df else f'UHE {df.hydro_id.iloc[0]}'
        self.arquivo.set(str(base.caminho.resolve()))
        parcial = ' | ATENÇÃO: contribuição parcial das montantes' if base.metadados.get('selecao_completa') is False else ''
        self.informacoes.set(f'{nome} | UHE {df.hydro_id.iloc[0]} | {len(df):,} linhas | '
                             f'{df.scenario_id.nunique()} cenários | {df.stage_id.nunique()} estágios{parcial}')
        for combo, coluna in [(self.cenario, 'scenario_id'), (self.estagio, 'stage_id')]:
            combo.configure(values=[TODOS] + [str(v) for v in sorted(df[coluna].unique())], state='readonly')
            combo.set(TODOS)
        self.metrica.configure(values=[f'{rotulo(c)} ({unidade(c)})' for c in base.metricas], state='readonly')
        self.metrica.current(0)
        self.exportar_botao.configure(state='normal')
        self.html_botao.configure(state='normal')
        self.meta.configure(state='normal')
        self.meta.delete('1.0', 'end')
        self.meta.insert('end', 'Os IDs são os originais. Vazões em m³/s, volumes em hm³ e potência em MW.\n'
                         'Metas e volumes de referência nulos significam: fora do período de enchimento.\n'
                         'P10 e P90 são percentis empíricos entre cenários, não probabilidades de excedência.\n'
                         'O fim de cada estágio é exclusivo. Nenhum arquivo de origem é alterado.\n\n'
                         + (json.dumps(base.metadados, ensure_ascii=False, indent=2) if base.metadados
                            else 'Arquivo sem metadados extrator_hydros. Informações obtidas das colunas.'))
        self.meta.configure(state='disabled')
        self.atualizar()

    def filtros(self):
        return tuple(None if c.get() == TODOS else int(c.get()) for c in [self.cenario, self.estagio])

    def atualizar(self, *_):
        if self.base is None:
            return
        self.pagina = 0
        cenario, estagio = self.filtros()
        metrica = self.base.metricas[self.metrica.current()]
        medida = unidade(metrica)
        self.filtrados = self.base.filtrar(cenario, estagio)
        df = self.filtrados
        valores = df[metrica].dropna()
        if len(valores):
            self.contagem.set(f'{len(df):,} linhas no filtro | {len(valores):,} valores aplicáveis | '
                              f'média: {valores.mean():,.3f} {medida}')
        else:
            self.contagem.set('Grandeza sem valores aplicáveis neste filtro.' if len(df)
                              else 'Nenhuma observação neste filtro.')
        eixo, canvas = self.figuras[0]
        eixo.clear()
        resumo = self.base.resumo(metrica, cenario, estagio)
        if cenario is None and len(valores):
            x = resumo.index.to_numpy()
            eixo.fill_between(x, resumo.p10.to_numpy(), resumo.p90.to_numpy(), color='#3b82f6', alpha=.18, label='P10–P90')
            eixo.plot(x, resumo.media, color='#1d4ed8', marker='.', label='Média')
            eixo.plot(x, resumo.mediana, color='#0f766e', linestyle='--', label='Mediana (P50)')
            eixo.legend(loc='best')
        elif len(valores):
            eixo.plot(df.stage_id, df[metrica], color='#1d4ed8', marker='o', markersize=4, label=f'Cenário {cenario}')
            eixo.legend(loc='best')
        eixo.set(title=rotulo(metrica), xlabel='Estágio (ID original)', ylabel=f'{rotulo(metrica)} ({medida})')
        eixo.xaxis.set_major_locator(MaxNLocator(integer=True))
        eixo.grid(alpha=.2)
        canvas.draw_idle()
        eixo, canvas = self.figuras[1]
        eixo.clear()
        if len(valores):
            eixo.hist(valores, bins=min(40, max(1, int(len(valores) ** .5))), color='#0f766e', edgecolor='white')
        eixo.set(title=f'{rotulo(metrica)} — observações do filtro', xlabel=f'{rotulo(metrica)} ({medida})', ylabel='Número de observações')
        eixo.grid(axis='y', alpha=.2)
        canvas.draw_idle()
        self.atualizar_tabela()
        self.status.set('Leitura concluída. Use a barra dos gráficos para zoom e salvar imagens.')

    def mudar_pagina(self, deslocamento):
        self.pagina += deslocamento
        self.atualizar_tabela()

    def atualizar_tabela(self):
        df = self.filtrados
        paginas = max(1, (len(df) + TAMANHO_PAGINA - 1) // TAMANHO_PAGINA)
        self.pagina = max(0, min(self.pagina, paginas - 1))
        self.tabela.delete(*self.tabela.get_children())
        self.tabela.configure(columns=list(df.columns))
        for coluna in df:
            self.tabela.heading(coluna, text=coluna)
            self.tabela.column(coluna, width=180 if coluna.endswith(('_m3s', '_hm3', '_mw')) else 120, stretch=False)
        inicio = self.pagina * TAMANHO_PAGINA
        for linha in df.iloc[inicio:inicio + TAMANHO_PAGINA].itertuples(index=False, name=None):
            self.tabela.insert('', 'end', values=['N/A' if pd.isna(v) else f'{v:.4f}' if isinstance(v, float)
                                                 else str(v) for v in linha])
        self.paginacao.set(f'Página {self.pagina + 1} de {paginas} | até {TAMANHO_PAGINA} linhas por página')
        self.anterior.configure(state='normal' if self.pagina else 'disabled')
        self.proxima.configure(state='normal' if self.pagina + 1 < paginas else 'disabled')

    def exportar_html(self):
        destino = filedialog.asksaveasfilename(parent=self, title='Salvar HTML com todos os cenários e estágios',
                                              initialfile=self.base.caminho.stem + '_grafico.html',
                                              defaultextension='.html', filetypes=[('HTML', '*.html')])
        if not destino:
            return
        base = self.base
        cenario = None if self.cenario.get() == TODOS else int(self.cenario.get())
        self.html_botao.configure(state='disabled')
        self.status.set('Gerando HTML com todos os cenários e estágios...')

        def executar():
            try:
                self.fila_html.put((gerar_html(base, destino, cenario), None))
            except Exception as erro:
                self.fila_html.put((None, str(erro)))
        threading.Thread(target=executar, daemon=True).start()

    def exportar(self):
        destino = filedialog.asksaveasfilename(parent=self, title='Exportar todas as linhas do filtro',
                                              defaultextension='.csv', filetypes=[('CSV', '*.csv')],
                                              initialfile=self.base.caminho.stem + '_filtrado.csv')
        if not destino:
            return
        try:
            self.base.exportar(destino, *self.filtros())
            self.status.set(f'CSV exportado: {destino} ({len(self.filtrados):,} linhas; todas as colunas).')
        except FileExistsError:
            messagebox.showerror('Arquivo já existe', 'Escolha um novo nome para preservar o arquivo existente.', parent=self)
        except Exception as erro:
            messagebox.showerror('Falha ao exportar', str(erro), parent=self)


def main():
    parser = argparse.ArgumentParser(description='Visualiza Parquets consolidados pelo Extrator HYDROS.')
    parser.add_argument('arquivo', nargs='?', type=Path, help='Parquet a abrir (opcional).')
    args = parser.parse_args()
    janela = tk.Tk()
    leitor = Leitor(janela)
    if args.arquivo:
        leitor.abrir(args.arquivo)
    janela.mainloop()


if __name__ == '__main__':
    main()
