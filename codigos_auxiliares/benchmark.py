#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEC107 - Etapa 2: benchmark sequencial ORIGINAL da Etapa 1 x MPI independente.

Execute na raiz do projeto:
  python codigos_auxiliares/benchmark.py --preset smoke
  python codigos_auxiliares/benchmark.py --compilar-apenas
  python codigos_auxiliares/benchmark.py --limpar-smoke
  python codigos_auxiliares/benchmark.py --preset smoke --dry-run
  python codigos_auxiliares/benchmark.py --preset oficial --dry-run
  python codigos_auxiliares/benchmark.py --preset padrao
  python codigos_auxiliares/benchmark.py --preset zoom --resume
  python codigos_auxiliares/benchmark.py --preset weak
  python codigos_auxiliares/benchmark.py --preset oficial

O sequencial original usa parâmetros em tempo de COMPILACAO e CSV fixo;
o MPI usa parâmetros de LINHA DE COMANDO e gera CSV por prefixo.
Os tempos vêm dos próprios programas C; o tempo de parede é apenas diagnóstico.
Todas as saídas oficiais permanecem em resultados/, gráficos serão gerados por analise.py.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

RAIZ = Path(__file__).resolve().parent.parent
SRC = RAIZ / 'src'
OUT = RAIZ / 'output'
EXES = OUT / 'exe'
TRAB = OUT / 'trabalho'
REF = OUT / 'ref'
RESULT = RAIZ / 'resultados'
CSV_OFICIAL = RESULT / 'resultados_consolidados.csv'
CSV_SMOKE = OUT / 'smoke' / 'smoke_resultados.csv'
SEQ_FONTE = SRC / 'mandelbrot_sequencial.c'
MPI_FONTE = SRC / 'mandelbrot_mpi.c'

COL_SEQ = ['versao','threads','schedule','chunk','width','height','max_iter',
           'real_a','real_b','imag_a','imag_b','tempo_calculo_s','tempo_escrita_s',
           'carga_min','carga_media','carga_max','fator_balanceamento',
           'trabalho_min','trabalho_media','trabalho_max']
COL_MPI = ['versao','estrategia','kernel','caso','processos','width','height','max_iter',
           'real_a','real_b','imag_a','imag_b','tempo_total_s','calculo_min_s',
           'calculo_medio_s','calculo_max_s','coleta_min_s','coleta_media_s',
           'coleta_max_s','tempo_escrita_s','fbc_calculo','trabalho_min',
           'trabalho_medio','trabalho_max','trabalho_total','resolucao_relogio_s',
           'chunk_linhas','tempo_montagem_s']
COL_RANK = ['rank','primeira_linha','linhas','pixels','trabalho_iteracoes',
            'tempo_calculo_s','tempo_coleta_s','tempo_total_local_s',
            'tempo_montagem_s','processador']
COLS = ['run_id','data_hora','fase','rep','escala','caso','width','height',
        'max_iter','versao','processos','estrategia','chunk_linhas',
        'tempo_calculo_s','tempo_total_s','tempo_escrita_s','calculo_min_s',
        'calculo_medio_s','calculo_max_s','coleta_min_s','coleta_media_s',
        'coleta_max_s','tempo_montagem_s','fator_balanceamento',
        'trabalho_min','trabalho_medio','trabalho_max','trabalho_total',
        'real_a','real_b','imag_a','imag_b','hash','hash_ok','config_ok',
        'tempo_wall_s','exe','ranks_csv']


def exigir(cond, msg):
    if not cond:
        raise RuntimeError(msg)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def cmd(c, cwd=None, timeout=1800, env=None):
    started = time.perf_counter()
    try:
        r = subprocess.run([str(v) for v in c], cwd=cwd, env=env, timeout=timeout,
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f'Timeout ({timeout}s): {c}') from e
    exigir(r.returncode == 0,
           f'Comando falhou ({r.returncode}): {" ".join(map(str,c))}\n{r.stdout[-1200:]}\n{r.stderr[-1600:]}')
    return r, time.perf_counter()-started


def linhas_csv(path, colunas):
    exigir(path.is_file(), f'Arquivo ausente: {path}')
    with path.open(encoding='utf-8', newline='') as f:
        leitor = csv.DictReader(f)
        exigir(leitor.fieldnames == colunas,
               f'Cabeçalho incompatível em {path.name}: {leitor.fieldnames}')
        registros = list(leitor)
    exigir(len(registros) == 1, f'{path.name}: esperava somente uma linha; vieram {len(registros)}')
    return registros[0]


def seq_flags(args, caso, res):
    flags = ['-O2','-fopenmp','-ffp-contract=off']
    # Preserve os flags de cálculo da Etapa 1 em x86 32-bit.
    if args.sse2:
        flags += ['-msse2','-mfpmath=sse']
    flags += [f'-DWIDTH={res}', f'-DHEIGHT={res}']
    if caso == 'zoom':
        flags.append('-DCASO_ZOOM')
    return flags


def sequencial_exe(args, caso, res):
    flags = seq_flags(args, caso, res)
    exe = EXES / f'sequencial_{caso}_{res}{".exe" if os.name == "nt" else ""}'
    chave = hashlib.sha256(SEQ_FONTE.read_bytes() + repr([args.gcc,flags]).encode()).hexdigest()
    marca = Path(str(exe)+'.build')
    if exe.is_file() and marca.is_file() and marca.read_text() == chave:
        return exe
    print(f'Compilando sequencial original: {exe.name}', flush=True)
    cmd([args.gcc,*flags,str(SEQ_FONTE),'-lm','-o',str(exe)])
    marca.write_text(chave,encoding='ascii')
    return exe


def compilar_msvc(args, flags):
    """Configura vcvars64 e chama cl no MESMO cmd.exe, sem transportar PATH.

    Evita erros de aspas do PowerShell e problemas de Path/PATH do Windows.
    """
    bat = Path(args.vcvars64).expanduser() if args.vcvars64 else None
    if bat is None:
        candidatos = [
            Path(r'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat'),
            Path(r'C:\Program Files\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat'),
        ]
        bat = next((p for p in candidatos if p.is_file()), None)
    if bat is None:
        exigir(shutil.which('cl'),
               'MSVC não encontrado. Instale Build Tools com C++ ou informe --vcvars64.')
        cmd(['cl', *flags], cwd=RAIZ)
        return
    exigir(bat.is_file(), f'Arquivo vcvars64.bat não encontrado: {bat}')
    # O caminho da raiz pode conter caracteres Unicode (ex.: "Ciência").
    # Um arquivo .cmd codificado em UTF-8 não interpreta esses caracteres
    # corretamente no CMD padrão. Por isso, usamos caminhos relativos ao
    # diretório de trabalho, que o Python estabelece via API Unicode.
    def relativo_projeto(valor):
        caminho = Path(valor)
        try:
            return str(caminho.relative_to(RAIZ))
        except ValueError:
            return str(caminho)

    flags_cmd = []
    for flag in flags:
        if flag == str(MPI_FONTE):
            flags_cmd.append(relativo_projeto(MPI_FONTE))
        elif flag.startswith('/Fo') or flag.startswith('/Fe'):
            flags_cmd.append(flag[:3] + relativo_projeto(flag[3:]))
        else:
            flags_cmd.append(flag)

    linha_cl = subprocess.list2cmdline(['cl', *flags_cmd])
    with tempfile.TemporaryDirectory(prefix='mandelbrot_msvc_') as pasta_tmp:
        script = Path(pasta_tmp) / 'compilar_mpi.cmd'
        script.write_text(
            '@echo off\n'
            f'call "{bat}" >nul\n'
            'if errorlevel 1 exit /b 1\n'
            f'{linha_cl}\n'
            'exit /b %errorlevel%\n',
            encoding='ascii',
        )
        # O CMD parte da raiz do projeto e recebe somente caminhos ASCII
        # relativos nos parâmetros da compilação.
        cmd(['cmd.exe', '/d', '/c', str(script)], cwd=RAIZ, timeout=args.timeout)


def mpi_exe(args):
    if args.mpi_exe:
        exe = Path(args.mpi_exe).expanduser().resolve()
        exigir(exe.is_file(), f'MPI não encontrado: {exe}')
        return exe

    exe = EXES / f'mandelbrot_mpi{".exe" if os.name == "nt" else ""}'
    marca = Path(str(exe) + '.build')
    if os.name == 'nt' and args.compilador_mpi in ('auto', 'msvc'):
        sdk = Path(args.msmpi_sdk).expanduser()
        inc = sdk / 'Include'
        lib = sdk / 'Lib' / 'x64'
        exigir((inc / 'mpi.h').is_file(), f'MS-MPI SDK sem mpi.h: {inc}')
        exigir((lib / 'msmpi.lib').is_file(), f'MS-MPI SDK sem msmpi.lib: {lib}')
        obj = EXES / 'mandelbrot_mpi.obj'
        flags = ['/nologo', '/O2', '/TC', '/fp:precise',
                 f'/I{inc}', str(MPI_FONTE), f'/Fo{obj}', f'/Fe{exe}',
                 '/link', f'/LIBPATH:{lib}', 'msmpi.lib']
        chave = hashlib.sha256(MPI_FONTE.read_bytes() +
                               repr(['msvc-x64', str(sdk), flags]).encode()).hexdigest()
        if not (exe.is_file() and marca.is_file() and marca.read_text() == chave):
            print('Compilando MPI com MSVC x64 + MS-MPI SDK...', flush=True)
            compilar_msvc(args, flags)
            marca.write_text(chave, encoding='ascii')
        return exe

    exigir(args.compilador_mpi != 'msvc', 'MSVC é suportado somente no Windows.')
    exigir(shutil.which(args.mpicc),
           f'Compilador {args.mpicc} não encontrado. Use --mpi-exe ou instale mpicc.')
    flags = ['-O2', '-std=c11', '-ffp-contract=off', '-Wall', '-Wextra']
    if args.sse2:
        flags += ['-msse2', '-mfpmath=sse']
    chave = hashlib.sha256(MPI_FONTE.read_bytes() +
                           repr([args.mpicc, flags]).encode()).hexdigest()
    if not (exe.is_file() and marca.is_file() and marca.read_text() == chave):
        print('Compilando MPI independente com mpicc...', flush=True)
        cmd([args.mpicc, *flags, str(MPI_FONTE), '-lm', '-o', str(exe)])
        marca.write_text(chave, encoding='ascii')
    return exe


def launcher(args):
    item = args.mpiexec or shutil.which('mpiexec') or shutil.which('mpirun')
    if not item and os.name == 'nt':
        item = r'C:\Program Files\Microsoft MPI\Bin\mpiexec.exe'
    exigir(item and Path(item).is_file(), 'mpiexec não localizado; use --mpiexec CAMINHO')
    return str(Path(item).resolve())


def lista_int(texto):
    xs = list(dict.fromkeys(int(x.strip()) for x in texto.split(',')))
    exigir(xs and all(x > 0 for x in xs), 'Lista precisa conter inteiros positivos')
    return xs


def planejar(args):
    smoke = args.preset == 'smoke'
    base = args.res or (64 if smoke else 4096)
    reps = args.reps if args.reps is not None else (2 if smoke else 5)
    ini = args.baseline_ini if args.baseline_ini is not None else (2 if smoke else 7)
    fim = args.baseline_fim if args.baseline_fim is not None else (1 if smoke else 3)
    ps = lista_int(args.processos or ('1,2,4' if smoke else '1,2,4,6,8,12'))
    chunks = lista_int(args.chunks)
    exigir(min(reps,ini,fim) > 0, 'Repetições e baselines precisam ser positivos')
    exigir(base >= 2, 'Resolução mínima 2x2')
    familia = [('forte','padrao'),('forte','zoom')]
    if args.preset in ('padrao','zoom'):
        familia = [('forte',args.preset)]
    elif args.preset == 'weak':
        familia = [('fraca','padrao')]
    elif args.preset in ('oficial','smoke'):
        familia.append(('fraca','padrao'))
    plano = []
    rng = random.Random(args.seed)
    for escala,caso in familia:
        pontos = [(base,ps)] if escala == 'forte' else [
            (max(2,int(round(base*math.sqrt(p)))),[p]) for p in ps]
        for res,procs in pontos:
            exigir(res*res <= 2147483647, f'Resolução {res} excede INT_MAX pixels do MPI')
            # A referencia é compilada especificamente para esta resolução e caso.
            problema = dict(escala=escala,caso=caso,width=res,height=res,
                            max_iter=5000 if caso == 'zoom' else 1000)
            if escala == 'forte':
                plano.extend({**problema, 'versao':'sequencial','processos':1,
                              'estrategia':'nenhum','chunk_linhas':0,'fase':'baseline_ini','rep':r}
                             for r in range(1,ini+1))
            else:
                plano.append({**problema,'versao':'sequencial','processos':1,
                              'estrategia':'nenhum','chunk_linhas':0,'fase':'referencia','rep':1})
            configs = [(p,'blocos',0) for p in procs]
            configs += [(p,'ciclica',c) for p in procs for c in chunks]
            for r in range(1,reps+1):
                rodada = list(configs)
                rng.shuffle(rodada)
                for p,estrategia,chunk in rodada:
                    plano.append({**problema,'versao':'mpi','processos':p,
                                  'estrategia':estrategia,'chunk_linhas':chunk,
                                  'fase':'medicao','rep':r})
            if escala == 'forte':
                plano.extend({**problema,'versao':'sequencial','processos':1,
                              'estrategia':'nenhum','chunk_linhas':0,'fase':'baseline_fim','rep':r}
                             for r in range(1,fim+1))
    for i,job in enumerate(plano,1):
        job['run_id'] = (f"{job['escala']}|{job['caso']}|{job['width']}|{job['versao']}|"
                         f"p{job['processos']}|{job['estrategia']}|c{job['chunk_linhas']}|"
                         f"{job['fase']}|r{job['rep']}")
        job['id'] = f'e{i:06d}'
    return plano


def carregar_existente(path,args):
    if path.is_file() and args.recomecar:
        backup = path.with_name(path.name+f'.bak.{int(time.time())}')
        shutil.move(path,backup)
        print(f'CSV anterior preservado em {backup.name}')
    if not path.exists():
        return {}, {}
    exigir(args.resume, f'{path} já existe: use --resume ou --recomecar')
    with path.open(encoding='utf-8',newline='') as f:
        leitor=csv.DictReader(f)
        exigir(leitor.fieldnames==COLS,'Formato de CSV anterior incompatível')
        rows=list(leitor)
    feitos={r['run_id']:r for r in rows}
    refs={}
    for r in rows:
        chave=(r['caso'],int(r['width']),int(r['height']),int(r['max_iter']))
        if r['versao']=='sequencial' and r['hash']:
            if chave in refs:
                exigir(refs[chave]==r['hash'],'Referências sequenciais divergentes no CSV anterior')
            refs[chave]=r['hash']
    return feitos,refs


def anexar(path,row):
    novo=not path.exists() or not path.stat().st_size
    with path.open('a',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=COLS)
        if novo: w.writeheader()
        w.writerow({c:row.get(c,'') for c in COLS})


def limpar_trabalho():
    TRAB.mkdir(parents=True,exist_ok=True)
    for p in TRAB.iterdir():
        if p.is_file():
            # Só arquivos temporários sob output/trabalho; não mexer em resultados históricos.
            p.unlink()


def limpar_smoke():
    """Remove apenas artefatos descartaveis; preserva executaveis e referencias.

    Nunca segue links simbolicos nem remove a pasta de trabalho ou smoke em si.
    """
    destinos = (OUT / 'smoke', TRAB)
    for pasta in destinos:
        # Protege contra alteracoes acidentais nas constantes de caminhos.
        exigir(pasta.parent.resolve() == OUT.resolve(),
               f'Destino de limpeza fora de output/: {pasta}')
        exigir(pasta.name in ('smoke', 'trabalho'),
               f'Pasta nao autorizada para limpeza: {pasta}')
        if pasta.is_symlink():
            raise RuntimeError(f'Limpeza recusada: pasta simbolica: {pasta}')
        if not pasta.exists():
            print(f'Ja esta vazia/ausente: {pasta.relative_to(RAIZ)}')
            continue
        exigir(pasta.is_dir(), f'Nao e uma pasta: {pasta}')
        removidos = 0
        for item in pasta.iterdir():
            if item.is_symlink() or item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
            else:
                raise RuntimeError(f'Tipo de arquivo inesperado; limpeza interrompida: {item}')
            removidos += 1
        print(f'Limpeza: {pasta.relative_to(RAIZ)} ({removidos} itens removidos)')
    print('Preservados: src/, codigos_auxiliares/, output/exe/, output/ref/ e resultados/.')


def guardar_binario(origem,destino):
    if origem.is_file() and origem.stat().st_size <= 100*1024*1024:
        REF.mkdir(parents=True,exist_ok=True)
        shutil.copy2(origem,REF/destino)


def executar(job,seq,mpi,launch,args,refs):
    limpar_trabalho()
    nome=job['id']
    env=os.environ.copy()
    if job['versao']=='sequencial':
        # O sequencial da Etapa 1 NÃO recebe flags CLI, e grava nomes fixos no cwd.
        env.pop('OMP_SCHEDULE',None)
        env['OMP_NUM_THREADS']='1'
        comando=[seq]
    else:
        prefixo=TRAB/nome
        comando=[launch,*args.mpi_arg,'-n',job['processos'],mpi,
                 '--caso',job['caso'],'--width',job['width'],'--height',job['height'],
                 '--max-iter',job['max_iter'],'--saida',prefixo,
                 '--estrategia',job['estrategia']]
        if job['chunk_linhas']:
            comando.extend(['--chunk',job['chunk_linhas']])
    _,wall=cmd(comando,cwd=TRAB,timeout=args.timeout,env=env)
    row={k:job[k] for k in ('run_id','fase','rep','escala','caso','width','height',
                           'max_iter','versao','processos','estrategia','chunk_linhas')}
    row['data_hora']=datetime.now().isoformat(timespec='seconds')
    row['tempo_wall_s']=f'{wall:.6f}'
    row['exe']=Path(seq if job['versao']=='sequencial' else mpi).name
    if job['versao']=='sequencial':
        m=linhas_csv(TRAB/'metricas_sequencial.csv',COL_SEQ)
        arq=TRAB/'mandelbrot_sequencial.bin'
        row.update(tempo_calculo_s=m['tempo_calculo_s'],tempo_total_s=m['tempo_calculo_s'],
                   tempo_escrita_s=m['tempo_escrita_s'],calculo_min_s=m['carga_min'],
                   calculo_medio_s=m['carga_media'],calculo_max_s=m['carga_max'],
                   coleta_min_s='0',coleta_media_s='0',coleta_max_s='0',tempo_montagem_s='0',
                   fator_balanceamento=m['fator_balanceamento'],
                   trabalho_min=m['trabalho_min'],trabalho_medio=m['trabalho_media'],
                   trabalho_max=m['trabalho_max'],trabalho_total=m['trabalho_max'],
                   real_a=m['real_a'],real_b=m['real_b'],imag_a=m['imag_a'],imag_b=m['imag_b'])
        config=(m['versao']=='sequencial' and int(m['threads'])==1 and
                int(m['width'])==job['width'] and int(m['height'])==job['height'] and
                int(m['max_iter'])==job['max_iter'])
    else:
        prefixo=TRAB/nome
        m=linhas_csv(Path(str(prefixo)+'_metricas.csv'),COL_MPI)
        ranks_path=Path(str(prefixo)+'_ranks.csv')
        with ranks_path.open(encoding='utf-8',newline='') as f:
            rd=csv.DictReader(f)
            exigir(rd.fieldnames==COL_RANK,'Colunas de ranks MPI inesperadas')
            ranks=list(rd)
        exigir(len(ranks)==job['processos'],'Quantidade de ranks inconsistente')
        arq=Path(str(prefixo)+'.bin')
        row.update(tempo_calculo_s=m['calculo_max_s'],tempo_total_s=m['tempo_total_s'],
                   tempo_escrita_s=m['tempo_escrita_s'],calculo_min_s=m['calculo_min_s'],
                   calculo_medio_s=m['calculo_medio_s'],calculo_max_s=m['calculo_max_s'],
                   coleta_min_s=m['coleta_min_s'],coleta_media_s=m['coleta_media_s'],
                   coleta_max_s=m['coleta_max_s'],tempo_montagem_s=m['tempo_montagem_s'],
                   fator_balanceamento=m['fbc_calculo'],trabalho_min=m['trabalho_min'],
                   trabalho_medio=m['trabalho_medio'],trabalho_max=m['trabalho_max'],
                   trabalho_total=m['trabalho_total'],real_a=m['real_a'],real_b=m['real_b'],
                   imag_a=m['imag_a'],imag_b=m['imag_b'])
        config=(m['versao']=='mpi' and m['caso']==job['caso'] and
                m['estrategia']==job['estrategia'] and
                int(m['processos'])==job['processos'] and
                int(m['chunk_linhas'])==job['chunk_linhas'] and
                int(m['width'])==job['width'] and int(m['height'])==job['height'] and
                int(m['max_iter'])==job['max_iter'])
        # CSV de ranks por run, fora dos temporários, para comunicação e balanceamento.
        id_estavel=hashlib.sha256(job['run_id'].encode('utf-8')).hexdigest()[:16]
        dest=RESULT/'ranks'/f"{job['caso']}_{job['width']}_{id_estavel}_ranks.csv"
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ranks_path,dest)
        row['ranks_csv']=str(dest.relative_to(RAIZ))
    exigir(arq.is_file() and arq.stat().st_size==job['width']*job['height']*4,
           f'Matriz binária ausente ou tamanho inválido: {arq}')
    row['hash']=sha256(arq)
    chave=(job['caso'],job['width'],job['height'],job['max_iter'])
    if chave not in refs:
        exigir(job['versao']=='sequencial','Falta referência sequencial antes da execução MPI')
        refs[chave]=row['hash']
    row['hash_ok']=str(row['hash']==refs[chave])
    row['config_ok']=str(bool(config))
    if job['versao']=='sequencial' and chave in refs:
        guardar_binario(arq,f"sequencial_{job['caso']}_{job['width']}.bin")
    if job['versao']=='mpi':
        guardar_binario(arq,f"mpi_{job['caso']}_{job['width']}_{job['estrategia']}_c{job['chunk_linhas']}.bin")
    return row


def registrar_ambiente(args,plan,csv_path,mpi,launch):
    destino=csv_path.with_name('ambiente.md') if csv_path==CSV_OFICIAL else csv_path.with_suffix('.ambiente.md')
    anterior=destino.read_text(encoding='utf-8') if destino.is_file() else ''
    separador='## Condições e observações manuais'
    manual=anterior[anterior.index(separador):] if separador in anterior else (
        separador+'\n- Plano de energia, temperatura, aplicações abertas e binding: (preencher)\n')
    dados=['# Ambiente do benchmark MPI','',
           f'- Registro: {datetime.now().isoformat(timespec="seconds")}',
           f'- Sistema: {platform.platform()}',f'- CPU: {platform.processor()}',
           f'- Processadores lógicos: {os.cpu_count()}',
           f'- GCC sequencial: {args.gcc}',
           f'- Flags sequencial: `-O2 -fopenmp -ffp-contract=off'+ (' -msse2 -mfpmath=sse' if args.sse2 else '')+'`',
           f'- Executável MPI: `{mpi}`',f'- MPI launcher: `{launch}`',
           f'- Fonte sequencial SHA-256: `{sha256(SEQ_FONTE)}`',
           f'- Fonte MPI SHA-256: `{sha256(MPI_FONTE)}`',
           f'- Repetições planejadas: {len(plan)}',
           f'- Chamada: `{" ".join(sys.argv)}`','', manual.rstrip(),'']
    destino.parent.mkdir(parents=True,exist_ok=True)
    destino.write_text('\n'.join(dados),encoding='utf-8')


def args_cli():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--preset', choices=['smoke','padrao','zoom','weak','oficial'],default='smoke')
    p.add_argument('--processos',help='Ex.: 1,2,4,6,8,12')
    p.add_argument('--chunks',default='1,4,16',help='Chunks cíclicos; blocos sempre usa chunk 0')
    p.add_argument('--res',type=int,help='Lado da imagem (personaliza o preset)')
    p.add_argument('--reps',type=int)
    p.add_argument('--baseline-ini',type=int)
    p.add_argument('--baseline-fim',type=int)
    p.add_argument('--seed',type=int,default=2026)
    p.add_argument('--timeout',type=float,default=1800)
    p.add_argument('--gcc',default='gcc',help='GCC com -fopenmp da Etapa 1')
    p.add_argument('--mpicc',default='mpicc',help='Compilador MPI para Linux/WSL')
    p.add_argument('--compilador-mpi',choices=['auto','msvc','mpicc'],default='auto',
                   help='No Windows, auto escolhe MSVC; no Linux, mpicc')
    p.add_argument('--vcvars64',help='Caminho opcional do vcvars64.bat do MSVC x64')
    p.add_argument('--msmpi-sdk',default=r'C:\Program Files (x86)\Microsoft SDKs\MPI',
                   help='Raiz do MS-MPI SDK no Windows')
    p.add_argument('--mpi-exe',help='Executável MPI já compilado, necessário se não houver mpicc')
    p.add_argument('--mpiexec',help='Caminho do launcher MPI')
    p.add_argument('--mpi-arg',action='append',default=[],help='Argumentos adicionais ao launcher')
    p.add_argument('--sse2',action=argparse.BooleanOptionalAction,default=True,
                   help='Mantém -msse2 -mfpmath=sse da Etapa 1 (use --no-sse2 em plataformas não x86)')
    p.add_argument('--csv',type=Path,help='Local do consolidado CSV')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--limpar-smoke',action='store_true',
                   help='Apaga somente output/smoke/ e output/trabalho/, sem compilar nem executar')
    p.add_argument('--compilar-apenas',action='store_true',
                   help='Compila/verifica apenas o executável MPI, sem executar testes ou gravar CSV')
    p.add_argument('--resume',action='store_true')
    p.add_argument('--recomecar',action='store_true')
    return p.parse_args()


def main():
    args=args_cli()
    if args.limpar_smoke:
        exigir(not any((args.dry_run, args.compilar_apenas, args.resume, args.recomecar, args.csv is not None)),
               '--limpar-smoke nao pode ser combinado com --dry-run, --compilar-apenas, --resume, --recomecar ou --csv')
        limpar_smoke()
        return 0
    exigir(not (args.resume and args.recomecar),'--resume e --recomecar são exclusivos')
    exigir(args.timeout>0,'Timeout deve ser positivo')
    plano=planejar(args)
    csv_path=args.csv.resolve() if args.csv else (CSV_SMOKE if args.preset=='smoke' else CSV_OFICIAL)
    print(f'Plano {args.preset}: {len(plano)} execuções; CSV: {csv_path}')
    if args.dry_run:
        for escala,caso,res in sorted({(j['escala'],j['caso'],j['width']) for j in plano}):
            print(f'  {escala:5s} {caso:6s} {res}x{res}')
        print('Dry-run: nenhum arquivo compilado, executado ou alterado.')
        return 0
    if args.compilar_apenas:
        exigir(MPI_FONTE.is_file(), f'Fonte MPI ausente: {MPI_FONTE}')
        EXES.mkdir(parents=True, exist_ok=True)
        destino_mpi = mpi_exe(args)
        print(f'MPI pronto: {destino_mpi}')
        print('Nenhum benchmark executado; nenhum CSV de resultados gravado.')
        return 0
    exigir(SEQ_FONTE.is_file() and MPI_FONTE.is_file(),
           f'Fontes obrigatórias ausentes em {SRC}: mandelbrot_sequencial.c / mandelbrot_mpi.c')
    exigir(shutil.which(args.gcc), f'GCC não encontrado: {args.gcc}')
    for d in (EXES,TRAB,REF,RESULT): d.mkdir(parents=True,exist_ok=True)
    feitos,refs=carregar_existente(csv_path,args)
    # Não fazemos comparações de desempenho com execuções sem integridade comprovada.
    jobs=[j for j in plano if j['run_id'] not in feitos]
    if not jobs:
        print('Nenhum job pendente.')
        return 0
    launch=launcher(args)
    mpi=mpi_exe(args)
    # O MPI não é recompilado por resolução. O sequencial original precisa ser.
    seqs={(j['caso'],j['width']):sequencial_exe(args,j['caso'],j['width']) for j in jobs}
    registrar_ambiente(args,plano,csv_path,mpi,launch)
    invalidos=0
    for i,j in enumerate(jobs,1):
        print(f"[{i}/{len(jobs)}] {j['versao']:10s} {j['caso']} {j['width']} "
              f"p={j['processos']} {j['estrategia']} c={j['chunk_linhas']} {j['fase']} r{j['rep']}",flush=True)
        try:
            linha=executar(j,seqs[(j['caso'],j['width'])],mpi,launch,args,refs)
            anexar(csv_path,linha)
            if linha['hash_ok']!='True' or linha['config_ok']!='True':
                invalidos+=1
                print(f"  ATENÇÃO: hash_ok={linha['hash_ok']} config_ok={linha['config_ok']}; NÃO USAR NO RELATÓRIO")
            else:
                print(f"  OK: total={float(linha['tempo_total_s']):.6f}s SHA-256={linha['hash'][:12]}")
        except (OSError,RuntimeError,subprocess.SubprocessError) as e:
            print(f'PAROU no job {j["run_id"]}: {e}',file=sys.stderr)
            print(f'CSV preservado: {csv_path} | use --resume após corrigir o problema',file=sys.stderr)
            return 1
    print(f'Finalizado. CSV: {csv_path} | execuções inválidas: {invalidos}')
    return 2 if invalidos else 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except (ValueError,OSError,RuntimeError) as e:
        print(f'ERRO: {e}',file=sys.stderr)
        sys.exit(1)
