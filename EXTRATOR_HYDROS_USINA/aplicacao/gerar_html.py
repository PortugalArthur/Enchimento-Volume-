"""Gera um HTML interativo e autônomo a partir do consolidado HYDROS."""
import argparse
from pathlib import Path
import sys
import webbrowser

from infraestrutura.preparar_ambiente import garantir_dependencias

garantir_dependencias({'numpy': 'numpy>=1.24', 'pandas': 'pandas>=2.0',
                      'pyarrow': 'pyarrow>=14', 'plotly': 'plotly>=5.18'})
from dados.leitor import Consolidado
from dados.grafico_html import gerar_html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arquivo', nargs='?', type=Path)
    parser.add_argument('--saida', type=Path)
    parser.add_argument('--cenario', type=int, help='Cenário inicialmente selecionado no HTML.')
    parser.add_argument('--nao-abrir', action='store_true')
    args = parser.parse_args()
    janela = None
    try:
        if args.arquivo is None or args.saida is None:
            import tkinter as tk
            from tkinter import filedialog
            janela = tk.Tk()
            janela.withdraw()
            if args.arquivo is None:
                escolhido = filedialog.askopenfilename(parent=janela, title='Selecionar consolidado HYDROS', filetypes=[('Parquet', '*.parquet')])
                if not escolhido:
                    return 0
                args.arquivo = Path(escolhido)
            if args.saida is None:
                escolhido = filedialog.asksaveasfilename(parent=janela, title='Salvar HTML interativo (escolha um nome novo)',
                                                       initialfile=args.arquivo.stem + '_grafico.html',
                                                       defaultextension='.html', filetypes=[('HTML', '*.html')])
                if not escolhido:
                    return 0
                args.saida = Path(escolhido)
        destino = gerar_html(Consolidado.abrir(args.arquivo), args.saida, args.cenario)
        print(f'HTML gerado: {destino.resolve()}')
        if not args.nao_abrir:
            webbrowser.open(destino.resolve().as_uri())
        return 0
    except Exception as erro:
        print(f'Não foi possível gerar o HTML: {erro}', file=sys.stderr)
        if janela is not None:
            from tkinter import messagebox
            messagebox.showerror('Falha ao gerar HTML', str(erro), parent=janela)
        return 1
    finally:
        if janela is not None:
            janela.destroy()


if __name__ == '__main__':
    raise SystemExit(main())
