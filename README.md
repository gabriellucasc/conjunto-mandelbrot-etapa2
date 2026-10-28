# Projeto 1 — Conjunto de Mandelbrot · Etapa 2 (MPI)

DEC107 — Processamento Paralelo · UESC · 2026.2

**Autores:** Gabriel Oliveira Lucas César · Ronaldo Ribeiro Porto Filho

## Sobre

Implementação do conjunto de Mandelbrot em C utilizando o método de *escape-time*, com a versão sequencial original da Etapa 1 e uma implementação paralela independente em MPI (*Message Passing Interface*).

O projeto avalia diferentes números de processos e duas estratégias estáticas de distribuição de linhas: **blocos contíguos** e **distribuição cíclica**, com *chunks* de 1, 4 e 16 linhas. Também investiga escalabilidade forte e fraca, balanceamento de carga e custo de coleta dos resultados.

## Estrutura do projeto

```text
conjunto-mandelbrot-etapa2/
├── src/
│   ├── mandelbrot_sequencial.c
│   └── mandelbrot_mpi.c
│
├── codigos_auxiliares/
│   ├── benchmark.py
│   ├── analise.py
│   ├── gera_mandelbrot.py
│   └── validar_professor.py
│
├── resultados/
│   ├── resultados_consolidados.csv
│   ├── ambiente.md
│   ├── validacao_referencia_professor.md
│   ├── ranks/
│   ├── tabelas/
│   └── graficos/
│
├── relatorio_etapa2.pdf
├── README.md
└── .gitignore
```

`gera_mandelbrot.py` foi fornecido pelo professor e é usado na validação externa. O código sequencial foi preservado da Etapa 1, sem alterações na lógica.

A pasta `output/` reúne executáveis, matrizes binárias de referência e arquivos temporários gerados localmente; não é destinada ao versionamento no Git.

## Ambiente

- Intel Core i5-12400F — 6 núcleos físicos e 12 processadores lógicos
- 32 GB de RAM
- Windows 11
- GCC 6.3.0/MinGW, com suporte a OpenMP, para o sequencial original
- MSVC x64 e Microsoft MPI (MS-MPI Runtime e SDK) para a versão MPI
- Python 3, NumPy, pandas e matplotlib

A opção `-fopenmp` na compilação sequencial é mantida para disponibilizar `omp_get_wtime()`; a versão de referência continua executando sequencialmente. As configurações e os registros da coleta estão em `resultados/ambiente.md`.

## Como executar

Execute os comandos a partir da raiz do repositório `conjunto-mandelbrot-etapa2/`.

### Teste rápido

```powershell
python codigos_auxiliares/benchmark.py --preset smoke
```

Os testes rápidos são separados dos resultados oficiais e gravados em `output/smoke/`.

### Verificar a compilação MPI

```powershell
python codigos_auxiliares/benchmark.py --compilar-apenas
```

No ambiente Windows utilizado, o script configura automaticamente o MSVC e compila a versão MPI com o MS-MPI SDK.

### Bateria experimental

```powershell
python codigos_auxiliares/benchmark.py --preset oficial --dry-run
python codigos_auxiliares/benchmark.py --preset oficial
```

O primeiro comando apenas apresenta o planejamento. O segundo executa a bateria; caso seja necessário retomar uma execução interrompida, utilize `--resume`. **A coleta oficial já foi concluída:** não é necessário executá-la novamente para consultar os resultados existentes.

### Gerar tabelas e gráficos

```powershell
python codigos_auxiliares/analise.py --nucleos-fisicos 6
```

As tabelas e os gráficos são salvos, respectivamente, em `resultados/tabelas/` e `resultados/graficos/`.

### Validar contra a referência do professor

```powershell
python codigos_auxiliares/validar_professor.py
```

O resultado da comparação externa está documentado em `resultados/validacao_referencia_professor.md`. Para limpar apenas os arquivos descartáveis de teste, sem apagar os resultados oficiais, utilize `python codigos_auxiliares/benchmark.py --limpar-smoke`.

## Resultados

A bateria oficial registrou **386 execuções válidas**, abrangendo **72 configurações MPI** e **15 gráficos de análise**. As configurações MPI foram medidas em cinco repetições, com resultados consolidados por mediana.

As matrizes produzidas pela versão MPI coincidiram exatamente com as matrizes da implementação sequencial nos testes oficiais, conforme verificação SHA-256. Na região padrão de 4096 × 4096, a distribuição cíclica com 12 processos alcançou *speedup* de aproximadamente **8,68×** e eficiência de **72,35%**.

A comparação com o gerador Python do professor, entretanto, **não atendeu integralmente aos limites externos de tolerância**. Mesmo após normalização diagnóstica da convenção de contagem de iterações, foram identificadas divergências já presentes na implementação sequencial da Etapa 1. Os detalhes e limites são apresentados no relatório de validação.

As durações de `MPI_Gatherv` incluem possível espera por processos mais lentos e não representam exclusivamente tempo de transferência de dados. As medições foram realizadas com MPI em um único computador, não em um cluster de máquinas distintas.

## Relatório

A metodologia, as tabelas, os gráficos e a discussão dos resultados estão reunidos em [`relatorio_etapa2.pdf`](relatorio_etapa2.pdf).

## Nota de Transparência sobre o Uso de IA

Declaramos que este projeto contou com auxílio do ChatGPT nas tarefas de planejamento da metodologia experimental, apoio à implementação e depuração, revisão dos scripts auxiliares de compilação, benchmark e análise, verificação de corretude, interpretação dos resultados e apoio à redação e revisão da documentação e do relatório.

Como autores, revisamos, testamos e validamos criticamente o conteúdo produzido com esse apoio, assumindo total responsabilidade pela correção lógica do código, pela precisão das medições e conclusões e pela integridade acadêmica do trabalho entregue.

**Gabriel Oliveira Lucas César — 29/10/2026**  
**Ronaldo Ribeiro Porto Filho — 29/10/2026**
