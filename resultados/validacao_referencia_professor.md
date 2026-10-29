# Validação da Etapa 2 contra a referência do professor

## Escopo e convenções

- Referência: `codigos_auxiliares/gera_mandelbrot.py` (SHA-256 `eb9a1ede4a344029822c1766ab5bb18decdeeaa7052e661264c27afd1bc93634`).
- Referência sequencial: **código original da Etapa 1**, preservado na Etapa 2.
- Matriz: int32 little-endian, row-major, 4096 × 4096; casos padrão e zoom.
- O professor registra índice de escape `i` (base zero); o C registra número de iterações `i + 1`.
- A normalização (`i -> i+1` para pixels que escapam) é aplicada **somente na comparação diagnóstica em memória**.
- Limites configurados no validador da Etapa 1: até 0.01% de pixels divergentes e diferença máxima de 1 iteração.
- **Conformidade formal não é automaticamente atestada por comparação normalizada**; registrar separadamente as diferenças brutas.
- Ambiente de validação: Python `3.13.3`, NumPy `2.4.3`, `Windows-11-10.0.26300-SP0`.

## Matrizes utilizadas

| Caso | Implementação | Arquivo | SHA-256 |
|---|---|---|---|
| padrao | Sequencial | `output/ref/sequencial_padrao_4096.bin` | `e50c4473b1256734f2a689a350cd056774c7a3aa5461a598bb12055c19c5c817` |
| padrao | MPI mpi_padrao_4096_blocos_c0.bin | `output/ref/mpi_padrao_4096_blocos_c0.bin` | `e50c4473b1256734f2a689a350cd056774c7a3aa5461a598bb12055c19c5c817` |
| padrao | MPI mpi_padrao_4096_ciclica_c1.bin | `output/ref/mpi_padrao_4096_ciclica_c1.bin` | `e50c4473b1256734f2a689a350cd056774c7a3aa5461a598bb12055c19c5c817` |
| zoom | Sequencial | `output/ref/sequencial_zoom_4096.bin` | `e69dba7173ce24c6a7da469a73d8ffbc979bc58101ec20458f333f9b8208dba2` |
| zoom | MPI mpi_zoom_4096_blocos_c0.bin | `output/ref/mpi_zoom_4096_blocos_c0.bin` | `e69dba7173ce24c6a7da469a73d8ffbc979bc58101ec20458f333f9b8208dba2` |
| zoom | MPI mpi_zoom_4096_ciclica_c1.bin | `output/ref/mpi_zoom_4096_ciclica_c1.bin` | `e69dba7173ce24c6a7da469a73d8ffbc979bc58101ec20458f333f9b8208dba2` |

## MPI versus sequencial (igualdade interna)

| Caso | MPI | Pixels divergentes | % divergente | Diferença máxima |
|---|---|---:|---:|---:|
| padrao | MPI mpi_padrao_4096_blocos_c0.bin | 0 | 0.000000% | 0 |
| padrao | MPI mpi_padrao_4096_ciclica_c1.bin | 0 | 0.000000% | 0 |
| zoom | MPI mpi_zoom_4096_blocos_c0.bin | 0 | 0.000000% | 0 |
| zoom | MPI mpi_zoom_4096_ciclica_c1.bin | 0 | 0.000000% | 0 |

## Padrão: comparação com professor (SEM normalização)

| Implementação | Pixels divergentes | % divergente | Diferença máxima | Situação |
|---|---:|---:|---:|---|
| Sequencial | 13962959 | 83.225721% | 461 | FORA DOS LIMITES |
| MPI mpi_padrao_4096_blocos_c0.bin | 13962959 | 83.225721% | 461 | FORA DOS LIMITES |
| MPI mpi_padrao_4096_ciclica_c1.bin | 13962959 | 83.225721% | 461 | FORA DOS LIMITES |

## Padrão: comparação diagnóstica (COM normalização)

| Implementação | Pixels divergentes | % divergente | Diferença máxima | Situação |
|---|---:|---:|---:|---|
| Sequencial | 786 | 0.004685% | 460 | FORA DOS LIMITES |

Exemplos de diferenças em `Sequencial`: (y=852, x=2598: ref=1000, C=806), (y=864, x=2542: ref=458, C=478), (y=902, x=2542: ref=1000, C=854), (y=908, x=2609: ref=475, C=468), (y=925, x=2474: ref=536, C=505).
| MPI mpi_padrao_4096_blocos_c0.bin | 786 | 0.004685% | 460 | FORA DOS LIMITES |

Exemplos de diferenças em `MPI mpi_padrao_4096_blocos_c0.bin`: (y=852, x=2598: ref=1000, C=806), (y=864, x=2542: ref=458, C=478), (y=902, x=2542: ref=1000, C=854), (y=908, x=2609: ref=475, C=468), (y=925, x=2474: ref=536, C=505).
| MPI mpi_padrao_4096_ciclica_c1.bin | 786 | 0.004685% | 460 | FORA DOS LIMITES |

Exemplos de diferenças em `MPI mpi_padrao_4096_ciclica_c1.bin`: (y=852, x=2598: ref=1000, C=806), (y=864, x=2542: ref=458, C=478), (y=902, x=2542: ref=1000, C=854), (y=908, x=2609: ref=475, C=468), (y=925, x=2474: ref=536, C=505).

## Zoom — vale dos cavalos-marinhos: comparação com professor (SEM normalização)

| Implementação | Pixels divergentes | % divergente | Diferença máxima | Situação |
|---|---:|---:|---:|---|
| Sequencial | 16772929 | 99.974447% | 1414 | FORA DOS LIMITES |
| MPI mpi_zoom_4096_blocos_c0.bin | 16772929 | 99.974447% | 1414 | FORA DOS LIMITES |
| MPI mpi_zoom_4096_ciclica_c1.bin | 16772929 | 99.974447% | 1414 | FORA DOS LIMITES |

## Zoom — vale dos cavalos-marinhos: comparação diagnóstica (COM normalização)

| Implementação | Pixels divergentes | % divergente | Diferença máxima | Situação |
|---|---:|---:|---:|---|
| Sequencial | 24242 | 0.144494% | 1415 | FORA DOS LIMITES |

Exemplos de diferenças em `Sequencial`: (y=0, x=46: ref=750, C=801), (y=0, x=108: ref=723, C=604), (y=0, x=114: ref=497, C=500), (y=0, x=150: ref=608, C=613), (y=0, x=329: ref=305, C=304).
| MPI mpi_zoom_4096_blocos_c0.bin | 24242 | 0.144494% | 1415 | FORA DOS LIMITES |

Exemplos de diferenças em `MPI mpi_zoom_4096_blocos_c0.bin`: (y=0, x=46: ref=750, C=801), (y=0, x=108: ref=723, C=604), (y=0, x=114: ref=497, C=500), (y=0, x=150: ref=608, C=613), (y=0, x=329: ref=305, C=304).
| MPI mpi_zoom_4096_ciclica_c1.bin | 24242 | 0.144494% | 1415 | FORA DOS LIMITES |

Exemplos de diferenças em `MPI mpi_zoom_4096_ciclica_c1.bin`: (y=0, x=46: ref=750, C=801), (y=0, x=108: ref=723, C=604), (y=0, x=114: ref=497, C=500), (y=0, x=150: ref=608, C=613), (y=0, x=329: ref=305, C=304).

## Conclusão

- As matrizes MPI são **idênticas** ao sequencial original nos arquivos examinados.
- Ao menos uma matriz ficou fora dos limites mesmo após normalização diagnóstica.
- Não foi modificada ou salva nenhuma matriz do professor e nenhum binário C foi alterado.
- A igualdade por SHA-256 no benchmark é uma validação de consistência interna; não substitui esta referência externa.
