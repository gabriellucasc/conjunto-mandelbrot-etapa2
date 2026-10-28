#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEC107 - Etapa 2 (MPI): analise de benchmarks e graficos.

Compativel com o benchmark.py SIMPLIFICADO da Etapa 2, que escreve:
  resultados/resultados_consolidados.csv (uma linha por execucao)
  resultados/ranks/*_ranks.csv (uma linha por rank em cada execucao MPI)
  output/ref/sequencial_{caso}_{res}.bin (referencia para custo por linha)

Exemplos (execute na raiz do projeto ou de qualquer diretorio):
  python codigos_auxiliares/analise.py
  python codigos_auxiliares/analise.py --csv output/smoke/smoke_resultados.csv
  python codigos_auxiliares/analise.py --etapa1 ../.../resultados/tabelas/resumo_completo.csv
  python codigos_auxiliares/analise.py --somente-tabelas

O script NAO executa benchmarks. Nao inventa resultados ausentes e nao promove
um smoke test a experimento oficial. A comparacao com OpenMP e opcional.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

RAIZ = Path(__file__).resolve().parent.parent
CSV_OFICIAL = RAIZ / 'resultados' / 'resultados_consolidados.csv'
PASTA_GRAFICOS = RAIZ / 'resultados' / 'graficos'
PASTA_TABELAS = RAIZ / 'resultados' / 'tabelas'
PASTA_REF = RAIZ / 'output' / 'ref'
RES_BASE = 4096
CASOS = {'padrao': 'Região padrão', 'zoom': 'Zoom (cavalos-marinhos)'}
ESTRATEGIAS = ['Blocos', 'Cíclica, chunk 1', 'Cíclica, chunk 4', 'Cíclica, chunk 16']
CORES = {'Blocos': '#d62728', 'Cíclica, chunk 1': '#ff7f0e',
         'Cíclica, chunk 4': '#9467bd', 'Cíclica, chunk 16': '#17becf'}
MARCAS = {'Blocos': 's', 'Cíclica, chunk 1': 'o',
          'Cíclica, chunk 4': '^', 'Cíclica, chunk 16': 'D'}


def rotulo(estrategia, chunk):
    return 'Blocos' if estrategia == 'blocos' else f'Cíclica, chunk {int(chunk)}'


def ler_dados(caminho: Path, permitir_invalidos: bool) -> pd.DataFrame:
    if not caminho.is_file():
        raise FileNotFoundError(f'CSV não encontrado: {caminho}. Execute benchmark.py primeiro.')
    df = pd.read_csv(caminho, dtype={'run_id': 'string', 'hash': 'string', 'ranks_csv': 'string'})
    obrigatorias = {'run_id', 'fase', 'rep', 'escala', 'caso', 'width', 'height', 'max_iter',
                    'versao', 'processos', 'estrategia', 'chunk_linhas', 'tempo_total_s',
                    'tempo_escrita_s', 'calculo_min_s', 'calculo_medio_s', 'calculo_max_s',
                    'coleta_max_s', 'fator_balanceamento', 'hash_ok', 'config_ok', 'ranks_csv'}
    faltando = sorted(obrigatorias - set(df.columns))
    if faltando:
        raise ValueError(f'CSV incompatível com o benchmark.py entregue. Faltam: {faltando}')
    if df.empty:
        raise ValueError('CSV está vazio; não há medições para analisar.')
    if df['run_id'].duplicated().any():
        raise ValueError('CSV contém run_id duplicado: verifique se o benchmark foi retomado corretamente.')
    for campo in ('hash_ok', 'config_ok'):
        df[campo] = df[campo].astype(str).str.strip().str.lower().eq('true')
    ruins = df[~(df.hash_ok & df.config_ok)]
    if len(ruins) and not permitir_invalidos:
        raise ValueError(f'{len(ruins)} execução(ões) sem hash/configuração válidos. '
                         'Corrija o benchmark antes de gerar gráficos oficiais; '
                         'use --permitir-invalidos somente para diagnóstico.')
    if len(ruins):
        print(f'AVISO: removendo {len(ruins)} execução(ões) inválidas da análise.', file=sys.stderr)
        df = df[df.hash_ok & df.config_ok].copy()
    if df.empty:
        raise ValueError('Não há execuções válidas no CSV.')
    numericas = ['rep', 'width', 'height', 'max_iter', 'processos', 'chunk_linhas',
                 'tempo_total_s', 'tempo_calculo_s', 'tempo_escrita_s', 'calculo_min_s',
                 'calculo_medio_s', 'calculo_max_s', 'coleta_min_s', 'coleta_media_s',
                 'coleta_max_s', 'tempo_montagem_s', 'fator_balanceamento',
                 'trabalho_min', 'trabalho_medio', 'trabalho_max', 'trabalho_total']
    for c in numericas:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    essenciais = ['width', 'height', 'processos', 'tempo_total_s', 'calculo_max_s']
    if df[essenciais].isna().any().any() or (df['tempo_total_s'] <= 0).any():
        raise ValueError('Há medições numéricas ausentes, inválidas ou não positivas.')
    df['politica'] = [rotulo(s, c) if v == 'mpi' else 'Sequencial'
                      for v, s, c in zip(df.versao, df.estrategia, df.chunk_linhas)]
    return df


def dados_ranks(df: pd.DataFrame, estrito: bool = True) -> pd.DataFrame:
    linhas = []
    for j in df[df.versao == 'mpi'].itertuples(index=False):
        nome = j.ranks_csv
        if pd.isna(nome) or not str(nome).strip():
            if estrito:
                raise ValueError(f'CSV de ranks ausente para {j.run_id}')
            continue
        path = Path(str(nome))
        if not path.is_absolute():
            path = RAIZ / path
        if not path.is_file():
            if estrito:
                raise FileNotFoundError(f'CSV de ranks não encontrado para {j.run_id}: {path}')
            continue
        with path.open(encoding='utf-8', newline='') as f:
            registros = list(csv.DictReader(f))
        if len(registros) != int(j.processos):
            raise ValueError(f'Número incorreto de ranks em {path}: {len(registros)}')
        for reg in registros:
            linha = {k: reg[k] for k in ('rank', 'linhas', 'trabalho_iteracoes',
                                         'tempo_calculo_s', 'tempo_coleta_s', 'tempo_total_local_s',
                                         'tempo_montagem_s')}
            linha.update(run_id=str(j.run_id), caso=j.caso, escala=j.escala,
                         width=int(j.width), processos=int(j.processos), politica=j.politica)
            linhas.append(linha)
    ranks = pd.DataFrame(linhas)
    if not ranks.empty:
        for k in ('rank', 'linhas', 'trabalho_iteracoes', 'tempo_calculo_s',
                  'tempo_coleta_s', 'tempo_total_local_s', 'tempo_montagem_s'):
            ranks[k] = pd.to_numeric(ranks[k], errors='raise')
    return ranks


def resumir(df: pd.DataFrame):
    problemas = ['escala', 'caso', 'width', 'height', 'max_iter']
    seq = df[df.versao == 'sequencial']
    if seq.empty:
        raise ValueError('Nenhuma referência sequencial disponível no CSV.')
    baselines = (seq.groupby(problemas, dropna=False)
                 .agg(n=('tempo_total_s', 'size'), t_seq_s=('tempo_total_s', 'median'),
                      t_seq_min_s=('tempo_total_s', 'min'),
                      t_seq_max_s=('tempo_total_s', 'max'),
                      escrita_seq_s=('tempo_escrita_s', 'median'))
                 .reset_index())
    antes = seq[seq.fase == 'baseline_ini'].groupby(problemas)['tempo_total_s'].median().rename('antes_s')
    depois = seq[seq.fase == 'baseline_fim'].groupby(problemas)['tempo_total_s'].median().rename('depois_s')
    baselines = baselines.merge(antes.reset_index(), on=problemas, how='left')
    baselines = baselines.merge(depois.reset_index(), on=problemas, how='left')
    baselines['deriva_pct'] = 100 * (baselines.depois_s / baselines.antes_s - 1)
    mpi = df[df.versao == 'mpi'].copy()
    if mpi.empty:
        raise ValueError('Nenhuma medição MPI encontrada.')
    grupos = problemas + ['processos', 'estrategia', 'chunk_linhas', 'politica']
    resumo = (mpi.groupby(grupos, dropna=False)
              .agg(n=('tempo_total_s', 'size'), t_med_s=('tempo_total_s', 'median'),
                   t_min_s=('tempo_total_s', 'min'), t_max_s=('tempo_total_s', 'max'),
                   t_media_s=('tempo_total_s', 'mean'), t_dp_s=('tempo_total_s', 'std'),
                   calculo_max_s=('calculo_max_s', 'median'),
                   fbc=('fator_balanceamento', 'median'),
                   trabalho_min=('trabalho_min', 'median'), trabalho_medio=('trabalho_medio', 'median'),
                   trabalho_max=('trabalho_max', 'median'),
                   coleta_max_s=('coleta_max_s', 'median'),
                   coleta_media_s=('coleta_media_s', 'median'),
                   montagem_s=('tempo_montagem_s', 'median'),
                   escrita_s=('tempo_escrita_s', 'median'))
              .reset_index())
    resumo = resumo.merge(baselines[problemas+['t_seq_s']], on=problemas, how='left', validate='many_to_one')
    if resumo.t_seq_s.isna().any():
        raise ValueError('Existem configurações MPI sem referência sequencial do mesmo caso/resolução.')
    resumo['speedup'] = resumo.t_seq_s / resumo.t_med_s
    resumo['speedup_min'] = resumo.t_seq_s / resumo.t_max_s
    resumo['speedup_max'] = resumo.t_seq_s / resumo.t_min_s
    resumo['eficiencia_pct'] = 100 * resumo.speedup / resumo.processos
    resumo['cv_pct'] = 100 * resumo.t_dp_s.fillna(0) / resumo.t_media_s
    p = resumo.processos.astype(float)
    resumo['karp_flatt'] = np.where(p > 1,
                                      (1 / resumo.speedup - 1 / p) / (1 - 1 / p), np.nan)
    resumo['fbc_trabalho'] = np.where(resumo.trabalho_max > 0,
                                       (resumo.trabalho_max - resumo.trabalho_min) / resumo.trabalho_max,
                                       0.0)
    # Medida aproximada da fração ocupada pelo MPI_Gatherv; NÃO é transmissão pura.
    resumo['coleta_pct_do_total'] = 100 * resumo.coleta_max_s / resumo.t_med_s
    # Weak scaling: T_MPI(1) / T_MPI(p) na MESMA estratégia, com resolução proporcional a sqrt(p).
    weak = resumo[resumo.escala == 'fraca'].copy()
    if not weak.empty:
        bases = weak[weak.processos == 1][['caso', 'estrategia', 'chunk_linhas', 't_med_s']].rename(
            columns={'t_med_s': 't_mpi_1_s'})
        if bases.duplicated(['caso', 'estrategia', 'chunk_linhas']).any():
            raise ValueError('Há múltiplas referências MPI p=1 para a mesma estratégia weak.')
        weak = weak.merge(bases, on=['caso','estrategia','chunk_linhas'], how='left')
        weak['eficiencia_fraca_pct'] = 100 * weak.t_mpi_1_s / weak.t_med_s
        weak['pixels_por_processo'] = weak.width * weak.height / weak.processos
    return resumo, baselines, weak


def tabelas(resumo, baselines, weak, ranks, destino):
    destino.mkdir(parents=True, exist_ok=True)
    resumo.to_csv(destino/'resumo_completo.csv', index=False)
    baselines.to_csv(destino/'baseline.csv', index=False)
    if not weak.empty:
        weak.to_csv(destino/'weak.csv', index=False)
    if not ranks.empty:
        ranks.to_csv(destino/'ranks.csv', index=False)
    forte = resumo[resumo.escala == 'forte']
    for caso in CASOS:
        f = forte[forte.caso == caso]
        if not f.empty:
            f.to_csv(destino/f'strong_{caso}.csv', index=False)
    resumo[['escala','caso','width','processos','politica','fbc','fbc_trabalho',
            'trabalho_min','trabalho_medio','trabalho_max']].to_csv(destino/'balanceamento.csv', index=False)
    resumo[['escala','caso','width','processos','politica','t_med_s','calculo_max_s',
            'coleta_max_s','coleta_media_s','montagem_s','escrita_s',
            'coleta_pct_do_total']].to_csv(destino/'comunicacao.csv', index=False)
    resumo[['escala','caso','width','processos','politica','n','cv_pct',
            't_min_s','t_med_s','t_max_s']].to_csv(destino/'qualidade.csv', index=False)


def salvar(fig, pasta, nome):
    pasta.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(pasta/nome, dpi=150)
    plt.close(fig)


def series(df):
    nomes = [x for x in ESTRATEGIAS if x in set(df.politica)]
    nomes += sorted(set(df.politica) - set(nomes))
    return [(nome, df[df.politica == nome].sort_values('processos')) for nome in nomes]


def formato(nome, i):
    return CORES.get(nome, plt.get_cmap('tab10')(i % 10)), MARCAS.get(nome, 'v')


def figura_strong(resumo, caso, metrica, pasta, nucleos):
    d = resumo[(resumo.escala == 'forte') & (resumo.caso == caso) & (resumo.width == RES_BASE)]
    if d.empty:
        return False
    fig, ax = plt.subplots(figsize=(7.5,4.6))
    campo = {'tempo':'t_med_s', 'speedup':'speedup', 'eficiencia':'eficiencia_pct'}[metrica]
    for i, (nome, v) in enumerate(series(d)):
        cor, mk = formato(nome,i)
        if metrica == 'speedup':
            erro = [v.speedup-v.speedup_min, v.speedup_max-v.speedup]
            ax.errorbar(v.processos,v[campo],yerr=erro,fmt=mk+'-',capsize=3,color=cor,label=nome)
        elif metrica == 'tempo':
            erro = [v.t_med_s-v.t_min_s, v.t_max_s-v.t_med_s]
            ax.errorbar(v.processos,v[campo],yerr=erro,fmt=mk+'-',capsize=3,color=cor,label=nome)
        else:
            ax.plot(v.processos,v[campo],mk+'-',color=cor,label=nome)
    if metrica == 'tempo':
        ax.axhline(float(d.t_seq_s.iloc[0]),linestyle='--',color='black',
                   label=f'Sequencial ({float(d.t_seq_s.iloc[0]):.2f} s)')
        ax.set_ylabel('Tempo total MPI (s), sem escrita')
    elif metrica == 'speedup':
        x1,x2 = min(1,int(d.processos.min())),int(d.processos.max())
        ax.plot([x1,x2],[x1,x2],'k--',label='ideal: S=p')
        ax.set_ylabel('Speedup')
    else:
        ax.axhline(100,ls='--',color='black',label='ideal: 100%')
        ax.set_ylabel('Eficiência (%)')
    ax.set_title(f'{metrica.capitalize()} × processos — {CASOS[caso]}')
    ax.set_xlabel('Processos MPI')
    ax.set_xticks(sorted(d.processos.unique()))
    if nucleos and min(d.processos)<=nucleos<=max(d.processos):
        ax.axvline(nucleos,color='gray',ls=':',lw=1,label=f'{nucleos} núcleos físicos')
    ax.grid(alpha=.25);ax.legend(fontsize=8)
    salvar(fig,pasta,f'strong_{metrica}_{caso}.png')
    return True


def figura_balanceamento(resumo, caso, pasta):
    d = resumo[(resumo.escala == 'forte') & (resumo.caso == caso) & (resumo.width == RES_BASE)]
    if d.empty: return False
    fig,ax=plt.subplots(figsize=(7.5,4.6))
    for i,(nome,v) in enumerate(series(d)):
        cor,mk=formato(nome,i)
        ax.plot(v.processos,v.fbc,mk+'-',color=cor,label=nome)
    ax.set(xlabel='Processos MPI',ylabel='FBC = (Tmax − Tmin) / Tmax',
           title=f'Desbalanceamento de cálculo — {CASOS[caso]}')
    ax.set_ylim(0,1.05);ax.set_xticks(sorted(d.processos.unique()));ax.grid(alpha=.25)
    ax.legend(fontsize=8)
    salvar(fig,pasta,f'fbc_processos_{caso}.png');return True


def figura_comunicacao(resumo, caso, pasta):
    d=resumo[(resumo.escala=='forte')&(resumo.caso==caso)&(resumo.width==RES_BASE)]
    if d.empty: return False
    fig,axs=plt.subplots(1,2,figsize=(11,4.5))
    for i,(nome,v) in enumerate(series(d)):
        cor,mk=formato(nome,i)
        axs[0].plot(v.processos,v.coleta_max_s,mk+'-',color=cor,label=nome)
        axs[1].plot(v.processos,v.montagem_s,mk+'-',color=cor,label=nome)
    for ax,ylabel in zip(axs,['Máx. duração de MPI_Gatherv (s)\n(inclui espera)','Montagem no root (s)']):
        ax.set_xlabel('Processos MPI');ax.set_ylabel(ylabel)
        ax.set_xticks(sorted(d.processos.unique()));ax.set_ylim(bottom=0);ax.grid(alpha=.25)
        ax.legend(fontsize=7)
    fig.suptitle(f'Coleta e montagem — {CASOS[caso]} (escrita excluída)')
    salvar(fig,pasta,f'comunicacao_{caso}.png');return True


def figura_ranks(resumo,ranks,caso,pasta):
    d=resumo[(resumo.escala=='forte')&(resumo.caso==caso)&(resumo.width==RES_BASE)]
    if d.empty or ranks.empty:return False
    p=int(d.processos.max())
    r=ranks[(ranks.escala=='forte')&(ranks.caso==caso)&(ranks.width==RES_BASE)&(ranks.processos==p)]
    if r.empty:return False
    g=r.groupby(['politica','rank'],as_index=False)['tempo_calculo_s'].median()
    fig,ax=plt.subplots(figsize=(7.5,4.6))
    for i,(nome,v) in enumerate([(n,g[g.politica==n].sort_values('rank')) for n,_ in series(d)]):
        if v.empty:continue
        cor,mk=formato(nome,i)
        ax.plot(v['rank'],v.tempo_calculo_s,mk+'-',color=cor,label=nome)
    ax.set(xlabel='Rank MPI',ylabel='Mediana do tempo de cálculo (s)',
           title=f'Tempo de cálculo por rank — {CASOS[caso]}, {p} processos')
    ax.set_xticks(range(p));ax.grid(alpha=.25);ax.legend(fontsize=8)
    salvar(fig,pasta,f'ranks_{caso}.png');return True


def figura_weak(weak,pasta,nucleos):
    d=weak[weak.caso=='padrao']
    if d.empty:return False
    fig,axs=plt.subplots(1,2,figsize=(11,4.5))
    for i,(nome,v) in enumerate(series(d)):
        cor,mk=formato(nome,i)
        axs[0].plot(v.processos,v.t_med_s,mk+'-',color=cor,label=nome)
        valid=v.dropna(subset=['eficiencia_fraca_pct'])
        if not valid.empty:
            axs[1].plot(valid.processos,valid.eficiencia_fraca_pct,mk+'-',color=cor,label=nome)
    axs[0].set_ylabel('Tempo total MPI (s)')
    axs[1].set_ylabel('Eficiência fraca (%)')
    axs[1].axhline(100,ls='--',color='black',label='ideal')
    for ax in axs:
        ax.set_xlabel('Processos MPI');ax.set_xticks(sorted(d.processos.unique()));ax.grid(alpha=.25)
        ax.legend(fontsize=7)
    axs[0].set_title('Weak scaling — tempo');axs[1].set_title('Weak scaling — eficiência')
    salvar(fig,pasta,'weak_scaling.png');return True


def figura_custo(caso,pasta):
    path=PASTA_REF/f'sequencial_{caso}_{RES_BASE}.bin'
    if not path.is_file():return False
    esperado=RES_BASE*RES_BASE*4
    if path.stat().st_size!=esperado:
        print(f'AVISO: {path} com tamanho inesperado; ignorando custo por linha.',file=sys.stderr)
        return False
    mm=np.memmap(path,dtype='<i4',mode='r',shape=(RES_BASE,RES_BASE))
    trabalho=np.asarray(mm.sum(axis=1,dtype=np.int64))
    fig,ax=plt.subplots(figsize=(7.5,4.6))
    ax.fill_between(range(RES_BASE),trabalho/1000,alpha=.6,step='mid')
    for k in (1,2,3):ax.axvline(k*RES_BASE/4,color='gray',ls='--',lw=.8)
    ax.set(xlabel='Linha da imagem (y)',ylabel='Soma das iterações (milhares)',
           title=f'Custo por linha — {CASOS[caso]}')
    ax.grid(alpha=.25);salvar(fig,pasta,f'custo_por_linha_{caso}.png')
    del mm
    return True


def comparar_openmp(resumo,arquivo,pasta_tabelas,pasta_graficos):
    """Comparacao contextual, sem misturar os tempos de baselines diferentes.

    Dados da Etapa 1 podem ter compilador, data e hardware distintos; este gráfico
    NÃO afirma equivalência experimental controlada entre paradigmas.
    """
    if not arquivo:return 0
    if not arquivo.is_file():
        raise FileNotFoundError(f'CSV OpenMP não encontrado: {arquivo}')
    d=pd.read_csv(arquivo)
    necessarias={'caso','width','threads','pol','t_med','t_seq','speedup','eficiencia'}
    if not necessarias.issubset(d.columns):
        raise ValueError('O CSV OpenMP não é o resumo_completo.csv da Etapa 1.')
    mpi=resumo[(resumo.escala=='forte')&(resumo.width==RES_BASE)]
    amp=d[(d.width==RES_BASE)&(d.pol.isin(['dynamic,1','static (blocos)']))]
    saidas=[]; n=0
    for caso in CASOS:
        fig,ax=plt.subplots(figsize=(7.5,4.6));existe=False
        for i,(nome,v) in enumerate(series(mpi[mpi.caso==caso])):
            cor,mk=formato(nome,i)
            ax.plot(v.processos,v.speedup,mk+'-',color=cor,label=f'MPI {nome}')
            for r in v.itertuples():
                saidas.append({'caso':caso,'paradigma':'MPI','configuracao':nome,'p':r.processos,
                               'tempo_s':r.t_med_s,'t_seq_s':r.t_seq_s,'speedup':r.speedup})
            existe=True
        for nome in ('dynamic,1','static (blocos)'):
            v=amp[(amp.caso==caso)&(amp.pol==nome)].sort_values('threads')
            if v.empty:continue
            ax.plot(v.threads,v.speedup,'x--',label=f'OpenMP {nome} (Etapa 1)')
            for r in v.itertuples():
                saidas.append({'caso':caso,'paradigma':'OpenMP','configuracao':nome,'p':r.threads,
                               'tempo_s':r.t_med,'t_seq_s':r.t_seq,'speedup':r.speedup})
            existe=True
        if existe:
            ax.set(xlabel='Processos MPI / threads OpenMP',ylabel='Speedup (baseline da própria coleta)',
                   title=f'MPI × OpenMP — {CASOS[caso]} (comparação contextual)')
            ax.grid(alpha=.25);ax.legend(fontsize=7)
            salvar(fig,pasta_graficos,f'mpi_x_openmp_speedup_{caso}.png');n+=1
        else:plt.close(fig)
    if saidas:pd.DataFrame(saidas).to_csv(pasta_tabelas/'mpi_x_openmp.csv',index=False)
    return n


def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--csv',type=Path,default=CSV_OFICIAL,help='CSV produzido pelo benchmark.py')
    p.add_argument('--graficos',type=Path,help='Pasta de saída dos PNG (padrão: graficos/)')
    p.add_argument('--tabelas',type=Path,help='Pasta de saída das tabelas (padrão: resultados/tabelas/)')
    p.add_argument('--etapa1',type=Path,help='CSV resumo_completo.csv da Etapa 1, para comparação contextual')
    p.add_argument('--nucleos-fisicos',type=int,default=0,help='Desenhar referência de núcleos físicos')
    p.add_argument('--somente-tabelas',action='store_true')
    p.add_argument('--permitir-invalidos',action='store_true',help='Diagnóstico: exclui execuções inválidas')
    a=p.parse_args()
    arquivo=a.csv.resolve()
    # Compatibilidade com o caminho antigo, caso ja existam medições de smoke.
    smoke=arquivo in {
        (RAIZ/'output'/'smoke'/'smoke_resultados.csv').resolve(),
        (RAIZ/'output'/'smoke_resultados.csv').resolve(),
    }
    graficos=a.graficos or ((RAIZ/'output'/'smoke'/'analise'/'graficos') if smoke else PASTA_GRAFICOS)
    destino_tabelas=a.tabelas or ((RAIZ/'output'/'smoke'/'analise'/'tabelas') if smoke else PASTA_TABELAS)
    df=ler_dados(arquivo,a.permitir_invalidos)
    ranks=dados_ranks(df)
    resumo,baselines,weak=resumir(df)
    tabelas_fn=destino_tabelas.resolve();graficos_fn=graficos.resolve()
    tabelas_fn.mkdir(parents=True,exist_ok=True)
    tabelas_exportadas=tabelas_fn
    tabelas(resumo,baselines,weak,ranks,tabelas_exportadas)
    print(f'{len(df)} execuções válidas; {len(resumo)} configurações MPI.')
    print(f'Tabelas: {tabelas_fn}')
    if a.somente_tabelas:
        return 0
    total=0
    for caso in CASOS:
        for m in ('tempo','speedup','eficiencia'):
            total+=figura_strong(resumo,caso,m,graficos_fn,a.nucleos_fisicos)
        total+=figura_balanceamento(resumo,caso,graficos_fn)
        total+=figura_comunicacao(resumo,caso,graficos_fn)
        total+=figura_ranks(resumo,ranks,caso,graficos_fn)
        total+=figura_custo(caso,graficos_fn)
    total+=figura_weak(weak,graficos_fn,a.nucleos_fisicos)
    if a.etapa1:
        total+=comparar_openmp(resumo,a.etapa1.resolve(),tabelas_fn,graficos_fn)
    print(f'{total} gráficos: {graficos_fn}')
    if smoke:
        print('ATENÇÃO: dados de smoke test; não utilizar no relatório como medições oficiais.')
    print('MPI_Gatherv inclui espera/sincronização; não interpretar como tempo puro de rede.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as e:
        print(f'ERRO: {e}',file=sys.stderr)
        sys.exit(1)
