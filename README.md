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
│   ├── graficos/
│   ├── imagens/
│   └── referencia_etapa1/
│
├── relatorio_etapa2.pdf
├── README.md
└── gitignore
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
python codigos_auxiliares/validar_professor.py --saida resultados/validacao_professor_nova.md
```

O destino da nova validação deve ser um arquivo ainda inexistente; para substituí-lo conscientemente, acrescente `--substituir`. A validação retorna código 1 quando encontra divergências ou limites ultrapassados. O resultado da comparação externa está documentado em `resultados/validacao_referencia_professor.md`. Para limpar apenas os arquivos descartáveis de teste, sem apagar os resultados oficiais, utilize `python codigos_auxiliares/benchmark.py --limpar-smoke`.

## Resultados

A bateria oficial registrou **386 execuções com verificação interna aprovada** (360 MPI e 26 sequenciais), abrangendo **72 configurações MPI** e **15 gráficos de análise**. As configurações MPI foram medidas em cinco repetições, com resultados consolidados por mediana.

As matrizes produzidas pela versão MPI coincidiram exatamente com as matrizes da implementação sequencial nos testes oficiais, conforme verificação SHA-256. Na região padrão de 4096 × 4096, a distribuição cíclica com 12 processos alcançou *speedup* de aproximadamente **8,68×** e eficiência de **72,35%**.

A comparação com o gerador Python do professor, entretanto, **não atendeu integralmente aos limites externos de tolerância**. Mesmo após normalização diagnóstica da convenção de contagem de iterações, foram identificadas divergências já presentes na implementação sequencial da Etapa 1. Os detalhes e limites são apresentados no relatório de validação.

As durações de `MPI_Gatherv` incluem possível espera por processos mais lentos e não representam exclusivamente tempo de transferência de dados. As medições foram realizadas com MPI em um único computador, não em um cluster de máquinas distintas.

As imagens auxiliares PGM do padrão e do zoom estão em `resultados/imagens/`, derivadas sem perda das contagens dos binários preservados. As referências históricas para a comparação OpenMP estão em `resultados/referencia_etapa1/`, e a tabela contextual em `resultados/tabelas/comparacao_openmp_contextual.csv`.

## Relatório

A metodologia, as tabelas, os gráficos e a discussão dos resultados estão reunidos em [relatorio_etapa2.pdf](relatorio_etapa2.pdf), disponível na raiz deste repositório, junto ao README e às pastas de código e resultados.

## Nota de Transparência sobre o Uso de IA

Declaramos que este projeto contou com o auxílio das ferramentas de IA **ChatGPT e Codex**, utilizadas por ambos os integrantes exclusivamente para as tarefas de apoio ao desenvolvimento, explicação, depuração e revisão do código e dos scripts; planejamento e automação dos testes; consolidação e conferência dos dados, métricas e gráficos; interpretação dos resultados e comparação com OpenMP; investigação e documentação das diferenças numéricas perante a referência do professor; e organização e revisão técnica, gramatical e estrutural do relatório, do README e da declaração de IA, incluindo a comparação conceitual com DGEMM.

Como autores, atestamos que revisamos, testamos e validamos criticamente todo o conteúdo gerado, assumindo total e exclusiva responsabilidade pela correção lógica do código, precisão dos relatórios de desempenho e integridade acadêmica do material entregue.

A validação crítica identificou divergências perante a referência do professor, documentadas no relatório e em `resultados/validacao_referencia_professor.md`; esta nota não implica aprovação no critério externo de corretude. A bateria oficial foi executada no computador de Gabriel e suas medições foram preservadas.

**Gabriel Oliveira Lucas César — 29/10/2026**  
**Ronaldo Ribeiro Porto Filho — 29/10/2026**
