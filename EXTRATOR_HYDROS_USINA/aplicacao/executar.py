"""Seletores gráficos e execução por linha de comando."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infraestrutura.preparar_ambiente import PASTA_PROJETO, garantir_dependencias

garantir_dependencias({'numpy': 'numpy>=1.24', 'pandas': 'pandas>=2.0', 'pyarrow': 'pyarrow>=14'})
from dados.extrator import carregar_deck, consolidar, encontrar_cenarios


class Seletor(ttk.Frame):
    def __init__(self, janela, deck, cenarios, hydros):
        super().__init__(janela, padding=16)
        self.pack(fill='both', expand=True)
        self.janela, self.deck, self.cenarios, self.hydros = janela, deck, cenarios, hydros
        self.identificadores, self.montantes = [], []
        self.fila, self.ocupado = queue.Queue(), False
        janela.title('Extrator HYDROS — usina e água de montante')
        janela.geometry('940x740')
        janela.minsize(800, 650)
        janela.protocol('WM_DELETE_WINDOW', self.fechar)
        ttk.Label(self, text=f'HYDROS: {hydros}', wraplength=880).pack(anchor='w')
        ttk.Label(self, text=f'Deck: {deck.pasta}', wraplength=880).pack(anchor='w')
        ttk.Label(self, text=f'{len(cenarios)} cenários encontrados. Os IDs originais serão preservados.').pack(anchor='w', pady=(4, 12))
        ttk.Label(self, text='1. Escolha a usina em análise (busque por nome ou ID):').pack(anchor='w')
        self.busca = tk.StringVar()
        self.entrada = ttk.Entry(self, textvariable=self.busca)
        self.entrada.pack(fill='x', pady=4)
        self.lista = self.criar_lista(8, tk.BROWSE)
        self.lista.bind('<<ListboxSelect>>', self.atualizar_montantes)
        self.busca.trace_add('write', self.filtrar)
        ttk.Label(self, text='2. Selecione as montantes DIRETAS que contribuirão para a soma:').pack(anchor='w', pady=(12, 4))
        ttk.Label(self, text='Todas são pré-selecionadas. Use Ctrl+clique para alterar. Usinas anteriores na cascata ficam fora da soma.', wraplength=880).pack(anchor='w')
        self.lista_montantes = self.criar_lista(5, tk.EXTENDED)
        self.aviso = tk.StringVar(value='Selecione a usina em análise.')
        ttk.Label(self, textvariable=self.aviso, wraplength=880).pack(anchor='w', pady=6)
        ttk.Label(self, text='Água de montante = turbinada + vertida das selecionadas, ponderadas pelas horas dos patamares.\n'
                              'A coluna mede essa contribuição; desvios e tempos de viagem não entram neste cálculo.', wraplength=880).pack(anchor='w', pady=6)
        self.botao = ttk.Button(self, text='Gerar Parquet da usina', command=self.gerar)
        self.botao.pack(anchor='w', pady=8)
        self.barra = ttk.Progressbar(self, mode='indeterminate')
        self.barra.pack(fill='x', pady=4)
        self.status = tk.StringVar(value='Pronto para selecionar.')
        ttk.Label(self, textvariable=self.status, wraplength=880).pack(anchor='w')
        self.filtrar()
        self.after(150, self.verificar_fila)

    def criar_lista(self, altura, modo):
        quadro = ttk.Frame(self)
        quadro.pack(fill='both', expand=True, pady=4)
        lista = tk.Listbox(quadro, height=altura, selectmode=modo, exportselection=False)
        rolagem = ttk.Scrollbar(quadro, orient='vertical', command=lista.yview)
        lista.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side='right', fill='y')
        lista.pack(side='left', fill='both', expand=True)
        return lista

    def filtrar(self, *_):
        consulta = self.busca.get().strip().casefold()
        self.identificadores = [hid for hid, h in sorted(self.deck.usinas.items(), key=lambda par: par[1]['name'])
                                if consulta in f"{hid} {h['name']}".casefold()]
        self.lista.delete(0, 'end')
        for hid in self.identificadores:
            self.lista.insert('end', f"{hid:03d} — {self.deck.usinas[hid]['name']}")
        self.lista_montantes.delete(0, 'end')
        self.montantes = []
        self.aviso.set('Selecione a usina em análise.')

    def atualizar_montantes(self, *_):
        selecao = self.lista.curselection()
        if not selecao:
            return
        hid = self.identificadores[selecao[0]]
        self.montantes = self.deck.montantes_diretas(hid)
        self.lista_montantes.delete(0, 'end')
        for montante in self.montantes:
            self.lista_montantes.insert('end', f"{montante:03d} — {self.deck.usinas[montante]['name']}")
        self.lista_montantes.selection_set(0, 'end')
        self.aviso.set(f'{len(self.montantes)} montante(s) direta(s) disponível(is).' if self.montantes else
                       'Usina de cabeceira: a água de montante será zero em todos os estágios e cenários.')

    def gerar(self):
        selecao = self.lista.curselection()
        if not selecao:
            messagebox.showerror('Seleção necessária', 'Selecione a usina em análise.', parent=self.janela)
            return
        hid = self.identificadores[selecao[0]]
        montantes = [self.montantes[i] for i in self.lista_montantes.curselection()]
        if set(montantes) != set(self.montantes):
            messagebox.showinfo('Contribuição parcial', 'A coluna água de montante conterá apenas as usinas selecionadas. '
                                'Essa seleção parcial ficará registrada nos metadados do Parquet.', parent=self.janela)
        pasta_saida = PASTA_PROJETO/'outputs'
        pasta_saida.mkdir(exist_ok=True)
        escolhido = filedialog.asksaveasfilename(
            parent=self.janela, title='Salvar Parquet da usina', initialdir=str(pasta_saida),
            initialfile=f'hydros_uhe_{hid:03d}_{datetime.now():%Y%m%d_%H%M%S}.parquet',
            defaultextension='.parquet', filetypes=[('Parquet', '*.parquet')])
        if not escolhido:
            return
        self.ocupado = True
        for widget in [self.lista, self.lista_montantes, self.entrada, self.botao]:
            widget.configure(state='disabled')
        self.barra.start(20)
        self.status.set('Iniciando leitura e validação...')

        def executar():
            try:
                saida = consolidar(self.hydros, self.deck.pasta, hid, montantes, escolhido,
                                    cenarios_esperados=len(self.cenarios), sobrescrever=True,
                                    progresso=lambda texto: self.fila.put(('progresso', texto)))
                self.fila.put(('concluido', str(saida)))
            except Exception as erro:
                self.fila.put(('erro', str(erro)))
        threading.Thread(target=executar, daemon=True).start()

    def verificar_fila(self):
        try:
            while True:
                tipo, texto = self.fila.get_nowait()
                if tipo == 'progresso':
                    self.status.set(texto)
                    print(texto, flush=True)
                    continue
                self.ocupado = False
                self.barra.stop()
                for widget in [self.lista, self.lista_montantes, self.entrada, self.botao]:
                    widget.configure(state='normal')
                if tipo == 'erro':
                    self.status.set('Falha na validação. Confira os detalhes.')
                    messagebox.showerror('Não foi possível gerar o Parquet', texto, parent=self.janela)
                else:
                    self.status.set(f'Parquet salvo em: {texto}')
                    messagebox.showinfo('Parquet gerado', f'{len(self.cenarios)} linhas por estágio.\n\n{texto}', parent=self.janela)
        except queue.Empty:
            pass
        self.after(150, self.verificar_fila)

    def fechar(self):
        if self.ocupado:
            messagebox.showinfo('Processamento em andamento', 'Aguarde a conclusão para fechar a janela.', parent=self.janela)
        else:
            self.janela.destroy()


def interface():
    janela = tk.Tk()
    janela.withdraw()
    try:
        while True:
            pasta = filedialog.askdirectory(parent=janela, mustexist=True,
                                            title='1/2 — Selecione hydros (scenario_id=.../data.parquet)')
            if not pasta:
                return
            try:
                cenarios = encontrar_cenarios(pasta)
                break
            except ValueError as erro:
                messagebox.showerror('Pasta hydros incorreta', str(erro), parent=janela)
        messagebox.showinfo('Deck da mesma execução', 'Selecione a raiz do deck de entrada correspondente a esta saída.\n\n'
                            'system/hydros.json fornece nomes e ligações da cascata.\n'
                            'stages.json fornece as horas dos patamares para a média do estágio.', parent=janela)
        while True:
            pasta_deck = filedialog.askdirectory(parent=janela, mustexist=True, initialdir=str(Path(pasta).parent),
                                                title='2/2 — Deck de entrada (stages.json e system/hydros.json)')
            if not pasta_deck:
                return
            try:
                deck = carregar_deck(pasta_deck)
                break
            except (ValueError, KeyError, TypeError, OSError) as erro:
                messagebox.showerror('Deck incorreto', str(erro), parent=janela)
        Seletor(janela, deck, cenarios, Path(pasta))
        janela.deiconify()
        janela.mainloop()
    finally:
        try:
            janela.destroy()
        except tk.TclError:
            pass


def main():
    parser = argparse.ArgumentParser(description='Extrai uma UHE de HYDROS e soma as vazões de suas montantes diretas.')
    parser.add_argument('--hydros', type=Path)
    parser.add_argument('--deck', type=Path)
    parser.add_argument('--usina', type=int)
    parser.add_argument('--montantes', type=int, nargs='*', default=None,
                        help='IDs das montantes diretas. Omitido: todas; sem valores: nenhuma.')
    parser.add_argument('--saida', type=Path)
    parser.add_argument('--cenarios-esperados', type=int)
    parser.add_argument('--sobrescrever', action='store_true')
    args = parser.parse_args()
    modo_cli = any([args.hydros is not None, args.deck is not None, args.usina is not None,
                    args.saida is not None, args.montantes is not None, args.cenarios_esperados is not None, args.sobrescrever])
    if not modo_cli:
        interface()
        return 0
    if args.hydros is None or args.deck is None or args.usina is None or args.saida is None:
        parser.error('No modo CLI, informe --hydros, --deck, --usina e --saida.')
    try:
        deck = carregar_deck(args.deck)
        montantes = deck.montantes_diretas(args.usina) if args.montantes is None else args.montantes
        consolidar(args.hydros, args.deck, args.usina, montantes, args.saida,
                   cenarios_esperados=args.cenarios_esperados, sobrescrever=args.sobrescrever)
    except Exception as erro:
        print(f'ERRO: {erro}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
