#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEC107 / Etapa 2: sequencial original e MPI versus referencia do professor.

Executar a partir de qualquer diretorio:
  python codigos_auxiliares/validar_professor.py
  python codigos_auxiliares/validar_professor.py --caso padrao
  python codigos_auxiliares/validar_professor.py --caso zoom
  python codigos_auxiliares/validar_professor.py --listar
  python codigos_auxiliares/validar_professor.py --mpi caminho/arquivo.bin --caso padrao

Por padrao, descobre os .bin do benchmark.py em output/ref/ para cada caso oficial
(4096x4096) e compara todas as estrategias MPI encontradas. Exige pelo menos uma
matriz MPI por caso selecionado, a menos que --somente-sequencial seja indicado.

A referencia Python registra o indice i (base zero) do escape. O C registra i+1.
A normalizacao e SOMENTE diagnóstica e em memoria; os .bin nunca sao alterados.
Os criterios formais indicados no validador da Etapa 1 sao 0,01% de pixels e
no maximo 1 iteracao por pixel divergente, mas uma aprovacao apos normalizacao
NAO equivale automaticamente a conformidade formal da matriz C original.

Requer numpy. Nao compila/executa o programa C nem fabrica resultados medidos.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import inspect
from pathlib import Path
import platform
import sys
from typing import Callable

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
REF = RAIZ / 'output' / 'ref'
RESULTADOS = RAIZ / 'resultados'
PROFESSOR = Path(__file__).resolve().parent / 'gera_mandelbrot.py'
WIDTH = HEIGHT = 4096
LIMITE_PERCENTUAL = 0.01
LIMITE_DIFERENCA = 1


@dataclass(frozen=True)
class Caso:
    nome: str
    iteracoes: int
    real_min: float
    real_max: float
    imag_min: float
    imag_max: float


def casos_oficiais() -> dict[str, Caso]:
    cx, cy, meia_largura = -0.743643887, 0.131825904, 3.0e-3 / 2.0
    return {
        'padrao': Caso('Padrão', 1000, -2.0, 1.0, -1.5, 1.5),
        'zoom': Caso('Zoom — vale dos cavalos-marinhos', 5000,
                     cx-meia_largura, cx+meia_largura,
                     cy-meia_largura, cy+meia_largura),
    }


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open('rb') as arquivo:
        for bloco in iter(lambda: arquivo.read(8 * 1024 * 1024), b''):
            h.update(bloco)
    return h.hexdigest()


def carregar_binario(caminho: Path) -> np.memmap:
    if not caminho.is_file():
        raise FileNotFoundError(f'Binário ausente: {caminho}')
    esperado = WIDTH * HEIGHT * 4
    if caminho.stat().st_size != esperado:
        raise ValueError(f'{caminho.name}: tamanho {caminho.stat().st_size}; esperado {esperado} bytes')
    return np.memmap(caminho, dtype='<i4', mode='r', shape=(HEIGHT, WIDTH))


def carregar_funcao_professor(caminho: Path) -> Callable:
    """Extrai somente a funcao, sem executar o gerador de figuras."""
    codigo = caminho.read_text(encoding='utf-8')
    arvore = ast.parse(codigo, filename=str(caminho))
    funcoes = [n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name == 'mandelbrot']
    if len(funcoes) != 1:
        raise ValueError('Referencia deve conter exatamente uma funcao mandelbrot().')
    bloco = ast.Module(body=funcoes, type_ignores=[])
    ast.fix_missing_locations(bloco)
    namespace = {'np': np}
    exec(compile(bloco, str(caminho), 'exec'), namespace, namespace)
    return namespace['mandelbrot']


def calcular_professor(funcao: Callable, caso: Caso) -> np.ndarray:
    argumentos = (caso.real_min, caso.real_max, caso.imag_min, caso.imag_max,
                  WIDTH, HEIGHT, caso.iteracoes)
    assinatura = inspect.signature(funcao)
    if len(assinatura.parameters) != 7:
        raise ValueError(f'Assinatura da referência mudou: {assinatura}')
    resultado = np.asarray(funcao(*argumentos))
    if resultado.shape != (HEIGHT, WIDTH):
        raise ValueError(f'Referencia retornou matriz {resultado.shape}, esperado {(HEIGHT, WIDTH)}')
    if not np.issubdtype(resultado.dtype, np.integer):
        raise ValueError('Matriz da referência não contém contagens inteiras.')
    return resultado


def comparar(ref: np.ndarray, teste: np.ndarray, normalizar: bool = False,
             max_iter: int = 0) -> dict:
    """Comparacao por faixas; normalizacao apenas em bloco temporario."""
    diferentes = ate_um = acima_um = maior = 0
    linhas_divergentes = 0
    exemplos = []
    for y0 in range(0, HEIGHT, 128):
        y1 = min(y0 + 128, HEIGHT)
        aa = np.asarray(ref[y0:y1], dtype=np.int64)
        bb = np.asarray(teste[y0:y1], dtype=np.int64)
        if normalizar:
            aa = aa.copy()
            aa[aa < max_iter] += 1
        delta = np.abs(aa - bb)
        mascara = delta != 0
        n = int(np.count_nonzero(mascara))
        if n:
            diferentes += n
            linhas_divergentes += int(np.count_nonzero(mascara.any(axis=1)))
            ate_um += int(np.count_nonzero((delta == 1)))
            acima_um += int(np.count_nonzero(delta > 1))
            maior = max(maior, int(delta.max()))
            if len(exemplos) < 5:
                ys, xs = np.nonzero(mascara)
                for j in range(min(len(ys), 5 - len(exemplos))):
                    ly, x = int(ys[j]), int(xs[j])
                    exemplos.append((y0 + ly, x, int(aa[ly, x]), int(bb[ly, x])))
    percentual = 100.0 * diferentes / (WIDTH * HEIGHT)
    return dict(diferentes=diferentes, percentual=percentual, ate_1=ate_um,
                acima_1=acima_um, maior_diferenca=maior,
                linhas_divergentes=linhas_divergentes, exemplos=exemplos,
                identico=diferentes == 0,
                dentro_limites=(percentual <= LIMITE_PERCENTUAL and maior <= LIMITE_DIFERENCA))


def descobrir_mpi(caso: str) -> list[Path]:
    return sorted(REF.glob(f'mpi_{caso}_{WIDTH}_*.bin'))


def nome_relativo(caminho: Path) -> str:
    try:
        return caminho.resolve().relative_to(RAIZ.resolve()).as_posix()
    except ValueError:
        return str(caminho.resolve())


def fmt(m: dict) -> str:
    return (f"{m['diferentes']:,} pixels ({m['percentual']:.6f}%), "
            f"diferença máxima {m['maior_diferenca']}")


def linha_markdown(rotulo: str, m: dict) -> str:
    situacao = 'IDÊNTICO' if m['identico'] else ('DENTRO DOS LIMITES' if m['dentro_limites'] else 'FORA DOS LIMITES')
    return (f"| {rotulo} | {m['diferentes']} | {m['percentual']:.6f}% | "
            f"{m['maior_diferenca']} | {situacao} |")


def executar(args) -> int:
    casos = casos_oficiais()
    escolhidos = list(casos) if args.caso == 'ambos' else [args.caso]
    if args.mpi and len(escolhidos) != 1:
        raise ValueError('--mpi exige --caso padrao ou --caso zoom')
    if args.listar:
        for chave in escolhidos:
            print(f'[{chave}] sequencial: {REF / f"sequencial_{chave}_{WIDTH}.bin"}')
            for p in descobrir_mpi(chave):
                print(f'  MPI: {p}')
        return 0

    fonte = Path(args.professor).resolve()
    if not fonte.is_file():
        raise FileNotFoundError(f'Arquivo do professor não encontrado: {fonte}')
    fn = carregar_funcao_professor(fonte)
    resultados = []
    falha_interna = False
    falha_limites = False

    for chave in escolhidos:
        caso = casos[chave]
        seq_path = REF / f'sequencial_{chave}_{WIDTH}.bin'
        mpi_paths = [Path(args.mpi).resolve()] if args.mpi else descobrir_mpi(chave)
        if not mpi_paths and not args.somente_sequencial:
            raise FileNotFoundError(f'Nenhum MPI encontrado para {chave} em {REF}. Rode o benchmark oficial ou use --mpi.')
        seq = carregar_binario(seq_path)
        mpis = [(path, carregar_binario(path)) for path in mpi_paths] if not args.somente_sequencial else []

        print(f'[{caso.nome}] gerando referência Python do professor em memória...', flush=True)
        professor = calcular_professor(fn, caso)
        entradas = [(seq_path, seq, 'Sequencial')]
        entradas.extend((path, matriz, f'MPI {path.name}') for path, matriz in mpis)
        resultados_caso = []
        for path, matriz, rotulo in entradas:
            bruto = comparar(professor, matriz)
            normalizado = comparar(professor, matriz, normalizar=True, max_iter=caso.iteracoes)
            interno = comparar(seq, matriz) if path != seq_path else None
            digest = sha256(path)
            print(f'  {rotulo}: professor bruto: {fmt(bruto)}; professor normalizado: {fmt(normalizado)}')
            if interno is not None:
                print(f'    MPI x sequencial: {fmt(interno)}; SHA-256: {digest[:16]}')
                if not interno['identico']:
                    falha_interna = True
            if not normalizado['dentro_limites']:
                falha_limites = True
            resultados_caso.append(dict(path=path, rotulo=rotulo, hash=digest,
                                        bruto=bruto, normalizado=normalizado, interno=interno))
        resultados.append((chave, caso, resultados_caso))
        del professor, seq, mpis

    texto = [
        '# Validação da Etapa 2 contra a referência do professor', '',
        '## Escopo e convenções', '',
        f'- Referência: `{nome_relativo(fonte)}` (SHA-256 `{sha256(fonte)}`).',
        '- Referência sequencial: **código original da Etapa 1**, preservado na Etapa 2.',
        '- Matriz: int32 little-endian, row-major, 4096 × 4096; casos padrão e zoom.',
        '- O professor registra índice de escape `i` (base zero); o C registra número de iterações `i + 1`.',
        '- A normalização (`i -> i+1` para pixels que escapam) é aplicada **somente na comparação diagnóstica em memória**.',
        f'- Limites configurados no validador da Etapa 1: até {LIMITE_PERCENTUAL}% de pixels divergentes e diferença máxima de {LIMITE_DIFERENCA} iteração.',
        '- **Conformidade formal não é automaticamente atestada por comparação normalizada**; registrar separadamente as diferenças brutas.',
        f'- Ambiente de validação: Python `{platform.python_version()}`, NumPy `{np.__version__}`, `{platform.platform()}`.',
        '', '## Matrizes utilizadas', '',
        '| Caso | Implementação | Arquivo | SHA-256 |', '|---|---|---|---|',
    ]
    for chave, _, items in resultados:
        for item in items:
            texto.append(f"| {chave} | {item['rotulo']} | `{nome_relativo(item['path'])}` | `{item['hash']}` |")
    texto += ['', '## MPI versus sequencial (igualdade interna)', '',
              '| Caso | MPI | Pixels divergentes | % divergente | Diferença máxima |', '|---|---|---:|---:|---:|']
    for chave, _, items in resultados:
        for item in items:
            if item['interno'] is not None:
                x = item['interno']
                texto.append(f"| {chave} | {item['rotulo']} | {x['diferentes']} | {x['percentual']:.6f}% | {x['maior_diferenca']} |")
    for chave, caso, items in resultados:
        texto += ['', f'## {caso.nome}: comparação com professor (SEM normalização)', '',
                  '| Implementação | Pixels divergentes | % divergente | Diferença máxima | Situação |',
                  '|---|---:|---:|---:|---|']
        for item in items:
            texto.append(linha_markdown(item['rotulo'], item['bruto']))
        texto += ['', f'## {caso.nome}: comparação diagnóstica (COM normalização)', '',
                  '| Implementação | Pixels divergentes | % divergente | Diferença máxima | Situação |',
                  '|---|---:|---:|---:|---|']
        for item in items:
            texto.append(linha_markdown(item['rotulo'], item['normalizado']))
            if item['normalizado']['exemplos']:
                texto.append(f"\nExemplos de diferenças em `{item['rotulo']}`: " +
                             ', '.join(f'(y={y}, x={x}: ref={a}, C={b})'
                                       for y,x,a,b in item['normalizado']['exemplos']) + '.')
    texto += ['', '## Conclusão', '',
              ('- As matrizes MPI são **idênticas** ao sequencial original nos arquivos examinados.'
               if not falha_interna else '- **Há divergências** entre ao menos um MPI e o sequencial; investigar a distribuição/coleta.'),
              ('- Todas as matrizes examinadas ficaram dentro dos limites **após normalização diagnóstica**.'
               if not falha_limites else '- Ao menos uma matriz ficou fora dos limites mesmo após normalização diagnóstica.'),
              '- Não foi modificada ou salva nenhuma matriz do professor e nenhum binário C foi alterado.',
              '- A igualdade por SHA-256 no benchmark é uma validação de consistência interna; não substitui esta referência externa.',
              '']
    destino = Path(args.saida).resolve() if args.saida else RESULTADOS / 'validacao_referencia_professor.md'
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and not args.substituir:
        raise FileExistsError(f'{destino} já existe: informe --substituir para sobrescrever, ou --saida OUTRO.md')
    destino.write_text('\n'.join(texto), encoding='utf-8')
    print(f'Relatório: {destino}')
    if falha_interna or falha_limites:
        print('ATENÇÃO: houve divergência interna ou limite ultrapassado; consulte o relatório.')
        return 1
    print('Comparações diagnósticas concluídas; conformidade formal requer interpretação da convenção.')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--caso', choices=('ambos', 'padrao', 'zoom'), default='ambos')
    ap.add_argument('--mpi', help='Arquivo .bin específico (exige --caso padrao|zoom)')
    ap.add_argument('--professor', default=str(PROFESSOR), help='Caminho de gera_mandelbrot.py')
    ap.add_argument('--saida', help='Caminho Markdown para o relatório')
    ap.add_argument('--substituir', action='store_true', help='Autoriza sobrescrever o relatório existente')
    ap.add_argument('--somente-sequencial', action='store_true', help='Analisa só o sequencial C contra o professor')
    ap.add_argument('--listar', action='store_true', help='Lista matrizes disponíveis sem calcular a referência')
    args = ap.parse_args()
    try:
        return executar(args)
    except (OSError, ValueError, RuntimeError, MemoryError) as erro:
        print(f'ERRO: {erro}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())