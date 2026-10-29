#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define MB_CAMINHO_MAX 512
#define MB_NOME_MAX 256
#define MB_KERNEL "etapa1-v1"

typedef enum { MB_PADRAO = 0, MB_ZOOM = 1 } MbCaso;
typedef enum { MB_BLOCOS = 0, MB_CICLICA = 1 } MbEstrategia;

typedef struct {
    int width;
    int height;
    int max_iter;
    int caso;
    int ppm;
    int estrategia;
    int chunk;
    int distribuicao_informada;
    double real_a;
    double real_b;
    double imag_a;
    double imag_b;
    char saida[MB_CAMINHO_MAX];
} MbConfig;

typedef struct {
    int primeira_linha;
    int linhas;
} MbBloco;

typedef struct {
    int rank;
    int primeira_linha;
    int linhas;
    uint64_t trabalho;
    double calculo_s;
    /* Duracao da chamada Gatherv, incluindo eventual espera por outros ranks. */
    double coleta_s;
    /* Reordenacao no root; zero na estrategia por blocos e nos demais ranks. */
    double montagem_s;
    /* Duracao local ate a barreira apos coleta e eventual montagem. */
    double total_s;
    char processador[MB_NOME_MAX];
} MbMetricasRank;

typedef struct {
    const char *versao;
    const char *estrategia;
    const char *biblioteca_mpi;
    int processos;
    double total_s;
    double escrita_s;
    double resolucao_relogio_s;
    const MbMetricasRank *ranks;
} MbExecucao;

void mb_config_padrao(MbConfig *cfg, const char *prefixo);
/* Retorna 0 em sucesso, 1 para --help e -1 para argumentos invalidos. */
int mb_ler_argumentos(int argc, char **argv, MbConfig *cfg,
                     char *erro, size_t erro_cap);
void mb_ajuda(FILE *destino, const char *programa);
const char *mb_nome_caso(int caso);
const char *mb_nome_estrategia(int estrategia);
/* Retorna 1 se valido, 0 se invalido. Limite INT_MAX das contagens MPI. */
int mb_total_pixels(const MbConfig *cfg, size_t *total);
MbBloco mb_dividir_blocos(int altura, int processos, int rank);
int mb_quantidade_linhas(const MbConfig *cfg, int processos, int rank);
/* Indice global de uma linha no buffer local; -1 se inexistente. */
int mb_linha_global(const MbConfig *cfg, int processos, int rank, int local);
uint64_t mb_calcular_parte(const MbConfig *cfg, int processos, int rank,
                          int32_t *destino);
/* Buffers distintos; recebido agrupa as partes por rank, como MPI_Gatherv. */
void mb_montar_imagem(const MbConfig *cfg, int processos,
                      const int32_t *recebido, int32_t *imagem);
int32_t mb_escape(double cr, double ci, int max_iter);
uint64_t mb_calcular_linhas(const MbConfig *cfg, int primeira, int linhas,
                           int32_t *destino);
int32_t *mb_alocar_pixels(size_t quantidade);
double mb_agora(void);
double mb_resolucao_relogio(void);
double mb_fbc(double minimo, double maximo);
int mb_salvar_binario(const MbConfig *cfg, const int32_t *imagem,
                     char *erro, size_t erro_cap);
int mb_salvar_ppm(const MbConfig *cfg, const int32_t *imagem,
                 char *erro, size_t erro_cap);
int mb_salvar_metricas(const MbConfig *cfg, const MbExecucao *execucao,
                      char *erro, size_t erro_cap);



/* ===== Calculo e utilitarios utilizados exclusivamente pelo MPI ===== */
#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif


#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <time.h>
#endif

static void definir_regiao(MbConfig *cfg)
{
    if (cfg->caso == MB_ZOOM) {
        /* Literais da etapa 1: evita alterar o dominio por arredondamento. */
        cfg->real_a = -0.745143887;
        cfg->real_b = -0.742143887;
        cfg->imag_a = 0.130325904;
        cfg->imag_b = 0.133325904;
        if (cfg->height != cfg->width) {
            double meia_altura = 0.0015 * (double)cfg->height / cfg->width;
            cfg->imag_a = 0.131825904 - meia_altura;
            cfg->imag_b = 0.131825904 + meia_altura;
        }
    } else {
        cfg->real_a = -2.0;
        cfg->real_b = 1.0;
        cfg->imag_a = -1.5;
        cfg->imag_b = 1.5;
    }
}

void mb_config_padrao(MbConfig *cfg, const char *prefixo)
{
    memset(cfg, 0, sizeof(*cfg));
    cfg->width = cfg->height = 4096;
    cfg->max_iter = 1000;
    cfg->caso = MB_PADRAO;
    cfg->chunk = 1;
    snprintf(cfg->saida, sizeof(cfg->saida), "%s", prefixo);
    definir_regiao(cfg);
}

const char *mb_nome_caso(int caso)
{
    return caso == MB_ZOOM ? "zoom" : "padrao";
}

const char *mb_nome_estrategia(int estrategia)
{
    return estrategia == MB_CICLICA ? "ciclica" : "blocos";
}

static int ler_inteiro(const char *texto, int minimo, int *valor)
{
    char *fim;
    long numero;
    errno = 0;
    numero = strtol(texto, &fim, 10);
    if (errno || fim == texto || *fim != '\0' || numero < minimo || numero > INT_MAX)
        return 0;
    *valor = (int)numero;
    return 1;
}

int mb_ler_argumentos(int argc, char **argv, MbConfig *cfg,
                     char *erro, size_t erro_cap)
{
    int max_iter_informado = 0;
    int chunk_informado = 0;
    size_t total;
    for (int i = 1; i < argc; ++i) {
        const char *opcao = argv[i];
        const char *valor;
        if (strcmp(opcao, "--help") == 0 || strcmp(opcao, "-h") == 0) return 1;
        if (strcmp(opcao, "--ppm") == 0) {
            cfg->ppm = 1;
            continue;
        }
        if (strcmp(opcao, "--caso") != 0 && strcmp(opcao, "--width") != 0 &&
            strcmp(opcao, "--height") != 0 && strcmp(opcao, "--max-iter") != 0 &&
            strcmp(opcao, "--saida") != 0 && strcmp(opcao, "--estrategia") != 0 &&
            strcmp(opcao, "--chunk") != 0) {
            snprintf(erro, erro_cap, "Opcao desconhecida: %s", opcao);
            return -1;
        }
        if (++i >= argc) {
            snprintf(erro, erro_cap, "Falta o valor de %s", opcao);
            return -1;
        }
        valor = argv[i];
        if (strcmp(opcao, "--caso") == 0) {
            if (strcmp(valor, "padrao") == 0) cfg->caso = MB_PADRAO;
            else if (strcmp(valor, "zoom") == 0) cfg->caso = MB_ZOOM;
            else {
                snprintf(erro, erro_cap, "Caso deve ser padrao ou zoom.");
                return -1;
            }
        } else if (strcmp(opcao, "--estrategia") == 0) {
            cfg->distribuicao_informada = 1;
            if (strcmp(valor, "blocos") == 0) cfg->estrategia = MB_BLOCOS;
            else if (strcmp(valor, "ciclica") == 0) cfg->estrategia = MB_CICLICA;
            else {
                snprintf(erro, erro_cap, "Estrategia deve ser blocos ou ciclica.");
                return -1;
            }
        } else if (strcmp(opcao, "--saida") == 0) {
            if (!*valor || strlen(valor) >= sizeof(cfg->saida)) {
                snprintf(erro, erro_cap, "Prefixo de saida vazio ou muito longo.");
                return -1;
            }
            strcpy(cfg->saida, valor);
        } else {
            int numero;
            int minimo = (strcmp(opcao, "--max-iter") == 0 ||
                          strcmp(opcao, "--chunk") == 0) ? 1 : 2;
            if (!ler_inteiro(valor, minimo, &numero)) {
                snprintf(erro, erro_cap, "Valor invalido para %s: %s", opcao, valor);
                return -1;
            }
            if (strcmp(opcao, "--width") == 0) cfg->width = numero;
            else if (strcmp(opcao, "--height") == 0) cfg->height = numero;
            else if (strcmp(opcao, "--chunk") == 0) {
                cfg->chunk = numero;
                chunk_informado = cfg->distribuicao_informada = 1;
            }
            else {
                cfg->max_iter = numero;
                max_iter_informado = 1;
            }
        }
    }
    if (chunk_informado && cfg->estrategia != MB_CICLICA) {
        snprintf(erro, erro_cap, "--chunk requer --estrategia ciclica.");
        return -1;
    }
    if (!max_iter_informado) cfg->max_iter = cfg->caso == MB_ZOOM ? 5000 : 1000;
    if (!mb_total_pixels(cfg, &total)) {
        snprintf(erro, erro_cap,
                 "Dimensoes invalidas: minimo 2x2, produto <= INT_MAX e alocacao representavel.");
        return -1;
    }
    definir_regiao(cfg);
    return 0;
}

void mb_ajuda(FILE *destino, const char *programa)
{
    fprintf(destino,
            "Uso: %s [--caso padrao|zoom] [--width N] [--height N]\n"
            "       [--max-iter N] [--saida PREFIXO] [--ppm]\n"
            "MPI:   [--estrategia blocos|ciclica] [--chunk N]\n"
            "MPI usa blocos por padrao; chunk positivo vale apenas para ciclica (padrao 1).\n"
            "Padrao: 4096x4096, 1000 iteracoes (zoom: 5000).\n"
            "Sempre grava PREFIXO.bin, PREFIXO_metricas.csv, PREFIXO_ranks.csv\n"
            "e PREFIXO_ambiente.txt. --ppm acrescenta uma imagem P3.\n"
            "A pasta de destino deve existir; o prefixo identifica UMA execucao.\n"
            "Os arquivos desse prefixo sao substituidos em uma nova execucao.\n",
            programa);
}

int mb_total_pixels(const MbConfig *cfg, size_t *total)
{
    size_t n;
    if (cfg->width < 2 || cfg->height < 2) return 0;
    if ((size_t)cfg->height > SIZE_MAX / (size_t)cfg->width) return 0;
    n = (size_t)cfg->width * (size_t)cfg->height;
    if (n > INT_MAX || n > SIZE_MAX / sizeof(int32_t)) return 0;
    *total = n;
    return 1;
}

MbBloco mb_dividir_blocos(int altura, int processos, int rank)
{
    MbBloco b = {-1, 0};
    int base, resto;
    if (altura < 0 || processos < 1 || rank < 0 || rank >= processos) return b;
    base = altura / processos;
    resto = altura % processos;
    b.linhas = base + (rank < resto ? 1 : 0);
    b.primeira_linha = rank * base + (rank < resto ? rank : resto);
    return b;
}

int mb_quantidade_linhas(const MbConfig *cfg, int processos, int rank)
{
    int completos, resto, blocos;
    if (cfg->height < 0 || processos < 1 || rank < 0 || rank >= processos)
        return 0;
    if (cfg->estrategia == MB_BLOCOS)
        return mb_dividir_blocos(cfg->height, processos, rank).linhas;
    if (cfg->estrategia != MB_CICLICA || cfg->chunk < 1) return 0;
    completos = cfg->height / cfg->chunk;
    resto = cfg->height % cfg->chunk;
    blocos = completos / processos + (rank < completos % processos);
    return blocos * cfg->chunk + (rank == completos % processos ? resto : 0);
}

int mb_linha_global(const MbConfig *cfg, int processos, int rank, int local)
{
    if (local < 0 || local >= mb_quantidade_linhas(cfg, processos, rank)) return -1;
    if (cfg->estrategia == MB_BLOCOS)
        return mb_dividir_blocos(cfg->height, processos, rank).primeira_linha + local;
    /* Intermediarios largos evitam overflow quando chunk ou P sao grandes. */
    return (int)(((int64_t)(local / cfg->chunk) * processos + rank) * cfg->chunk
                 + local % cfg->chunk);
}

uint64_t mb_calcular_parte(const MbConfig *cfg, int processos, int rank,
                          int32_t *destino)
{
    int linhas = mb_quantidade_linhas(cfg, processos, rank);
    uint64_t trabalho = 0;
    for (int local = 0; local < linhas;) {
        int quantidade = linhas - local;
        if (cfg->estrategia == MB_CICLICA && quantidade > cfg->chunk)
            quantidade = cfg->chunk;
        trabalho += mb_calcular_linhas(cfg, mb_linha_global(cfg, processos, rank, local),
                                      quantidade, destino + (size_t)local * cfg->width);
        local += quantidade;
    }
    return trabalho;
}

void mb_montar_imagem(const MbConfig *cfg, int processos,
                      const int32_t *recebido, int32_t *imagem)
{
    size_t deslocamento = 0;
    for (int rank = 0; rank < processos; ++rank) {
        int linhas = mb_quantidade_linhas(cfg, processos, rank);
        for (int local = 0; local < linhas; ++local) {
            int global = mb_linha_global(cfg, processos, rank, local);
            memcpy(imagem + (size_t)global * cfg->width,
                   recebido + deslocamento + (size_t)local * cfg->width,
                   (size_t)cfg->width * sizeof(*imagem));
        }
        deslocamento += (size_t)linhas * cfg->width;
    }
}

int32_t mb_escape(double cr, double ci, int max_iter)
{
    double zr = 0.0, zi = 0.0;
    for (int i = 0; i < max_iter; ++i) {
        /* Mesma ordem aritmetica e contagem (i+1) da etapa 1. */
        double proximo_real = (zr * zr) - (zi * zi) + cr;
        double proximo_imag = (2 * zr * zi) + ci;
        if ((proximo_real * proximo_real) + (proximo_imag * proximo_imag) > 4)
            return (int32_t)(i + 1);
        zr = proximo_real;
        zi = proximo_imag;
    }
    return (int32_t)max_iter;
}

uint64_t mb_calcular_linhas(const MbConfig *cfg, int primeira, int linhas,
                           int32_t *destino)
{
    uint64_t trabalho = 0;
    for (int ly = 0; ly < linhas; ++ly) {
        int y = primeira + ly;
        double ci = cfg->imag_a + (((cfg->imag_b - cfg->imag_a) / (cfg->height - 1)) * y);
        for (int x = 0; x < cfg->width; ++x) {
            double cr = cfg->real_a + (((cfg->real_b - cfg->real_a) / (cfg->width - 1)) * x);
            int32_t iter = mb_escape(cr, ci, cfg->max_iter);
            destino[(size_t)ly * (size_t)cfg->width + (size_t)x] = iter;
            trabalho += (uint64_t)iter;
        }
    }
    return trabalho;
}

int32_t *mb_alocar_pixels(size_t quantidade)
{
    /* Um rank vazio ainda fornece um endereco valido ao MPI com count=0. */
    if (quantidade == 0) quantidade = 1;
    if (quantidade > SIZE_MAX / sizeof(int32_t)) return NULL;
    return (int32_t *)malloc(quantidade * sizeof(int32_t));
}

double mb_agora(void)
{
#ifdef _WIN32
    LARGE_INTEGER contador, frequencia;
    if (!QueryPerformanceFrequency(&frequencia) || !QueryPerformanceCounter(&contador)) {
        fprintf(stderr, "Falha no relogio de alta resolucao.\n");
        exit(EXIT_FAILURE);
    }
    return (double)contador.QuadPart / (double)frequencia.QuadPart;
#else
    struct timespec agora;
    if (clock_gettime(CLOCK_MONOTONIC, &agora) != 0) {
        perror("clock_gettime");
        exit(EXIT_FAILURE);
    }
    return (double)agora.tv_sec + (double)agora.tv_nsec * 1e-9;
#endif
}

double mb_resolucao_relogio(void)
{
#ifdef _WIN32
    LARGE_INTEGER frequencia;
    if (!QueryPerformanceFrequency(&frequencia)) return 0.0;
    return 1.0 / (double)frequencia.QuadPart;
#else
    struct timespec resolucao;
    if (clock_getres(CLOCK_MONOTONIC, &resolucao) != 0) return 0.0;
    return (double)resolucao.tv_sec + (double)resolucao.tv_nsec * 1e-9;
#endif
}

double mb_fbc(double minimo, double maximo)
{
    return maximo > 0.0 ? (maximo - minimo) / maximo : 0.0;
}

static FILE *abrir_saida(const MbConfig *cfg, const char *sufixo,
                         const char *modo, char *erro, size_t erro_cap)
{
    char caminho[MB_CAMINHO_MAX + 64];
    FILE *arquivo;
    snprintf(caminho, sizeof(caminho), "%s%s", cfg->saida, sufixo);
    arquivo = fopen(caminho, modo);
    if (!arquivo)
        snprintf(erro, erro_cap, "Nao foi possivel abrir %s: %s", caminho, strerror(errno));
    return arquivo;
}

static int fechar_saida(FILE *arquivo, char *erro, size_t erro_cap)
{
    int falhou = ferror(arquivo);
    if (fclose(arquivo) != 0) falhou = 1;
    if (falhou) snprintf(erro, erro_cap, "Erro ao gravar/fechar arquivo de saida.");
    return !falhou;
}

int mb_salvar_binario(const MbConfig *cfg, const int32_t *imagem,
                     char *erro, size_t erro_cap)
{
    size_t total;
    uint32_t teste_endian = 1;
    FILE *arquivo;
    if (!mb_total_pixels(cfg, &total)) {
        snprintf(erro, erro_cap, "Dimensoes invalidas na escrita da imagem.");
        return 0;
    }
    arquivo = abrir_saida(cfg, ".bin", "wb", erro, erro_cap);
    if (!arquivo) return 0;
    /* Contrato explicito: int32 little-endian, row-major, sem cabecalho. */
    if (*(const unsigned char *)&teste_endian == 1) {
        if (fwrite(imagem, sizeof(int32_t), total, arquivo) != total) {
            snprintf(erro, erro_cap, "Escrita incompleta da matriz binaria.");
            fclose(arquivo);
            return 0;
        }
    } else {
        for (size_t i = 0; i < total; ++i) {
            uint32_t v = (uint32_t)imagem[i];
            unsigned char bytes[4] = {(unsigned char)v, (unsigned char)(v >> 8),
                                      (unsigned char)(v >> 16), (unsigned char)(v >> 24)};
            if (fwrite(bytes, 1, 4, arquivo) != 4) {
                snprintf(erro, erro_cap, "Escrita incompleta da matriz binaria.");
                fclose(arquivo);
                return 0;
            }
        }
    }
    return fechar_saida(arquivo, erro, erro_cap);
}

int mb_salvar_ppm(const MbConfig *cfg, const int32_t *imagem,
                 char *erro, size_t erro_cap)
{
    FILE *arquivo = abrir_saida(cfg, ".ppm", "w", erro, erro_cap);
    if (!arquivo) return 0;
    fprintf(arquivo, "P3\n%d %d\n255\n", cfg->width, cfg->height);
    for (int y = 0; y < cfg->height && !ferror(arquivo); ++y) {
        for (int x = 0; x < cfg->width; ++x) {
            int32_t iter = imagem[(size_t)y * (size_t)cfg->width + (size_t)x];
            int r = 0, g = 0, b = 0;
            if (iter != cfg->max_iter) {
                double t = log(iter + 1.0) / log(cfg->max_iter + 1.0);
                r = (int)(255 * t * t);
                g = (int)(100 * t * t * t);
                b = (int)(255 * t);
            }
            fprintf(arquivo, "%d %d %d ", r, g, b);
        }
        fputc('\n', arquivo);
    }
    return fechar_saida(arquivo, erro, erro_cap);
}

static void campo_csv(FILE *arquivo, const char *valor)
{
    fputc('"', arquivo);
    for (; *valor; ++valor) {
        if (*valor == '"') fputc('"', arquivo);
        fputc(*valor, arquivo);
    }
    fputc('"', arquivo);
}

int mb_salvar_metricas(const MbConfig *cfg, const MbExecucao *e,
                      char *erro, size_t erro_cap)
{
    const MbMetricasRank *r = e->ranks;
    double cmin = r[0].calculo_s, cmax = cmin, csoma = 0.0;
    double gmin = r[0].coleta_s, gmax = gmin, gsoma = 0.0;
    uint64_t wmin = r[0].trabalho, wmax = wmin, wsoma = 0;
    FILE *arquivo;
    for (int p = 0; p < e->processos; ++p) {
        if (r[p].calculo_s < cmin) cmin = r[p].calculo_s;
        if (r[p].calculo_s > cmax) cmax = r[p].calculo_s;
        if (r[p].coleta_s < gmin) gmin = r[p].coleta_s;
        if (r[p].coleta_s > gmax) gmax = r[p].coleta_s;
        if (r[p].trabalho < wmin) wmin = r[p].trabalho;
        if (r[p].trabalho > wmax) wmax = r[p].trabalho;
        csoma += r[p].calculo_s;
        gsoma += r[p].coleta_s;
        wsoma += r[p].trabalho;
    }
    arquivo = abrir_saida(cfg, "_metricas.csv", "w", erro, erro_cap);
    if (!arquivo) return 0;
    fprintf(arquivo,
        "versao,estrategia,kernel,caso,processos,width,height,max_iter,"
        "real_a,real_b,imag_a,imag_b,tempo_total_s,"
        "calculo_min_s,calculo_medio_s,calculo_max_s,"
        "coleta_min_s,coleta_media_s,coleta_max_s,tempo_escrita_s,fbc_calculo,"
        "trabalho_min,trabalho_medio,trabalho_max,trabalho_total,resolucao_relogio_s,"
        "chunk_linhas,tempo_montagem_s\n");
    fprintf(arquivo,
        "%s,%s,%s,%s,%d,%d,%d,%d,%.17g,%.17g,%.17g,%.17g,"
        "%.9f,%.9f,%.9f,%.9f,%.9f,%.9f,%.9f,%.9f,%.9f,"
        "%" PRIu64 ",%.3f,%" PRIu64 ",%" PRIu64 ",%.17g,%d,%.9f\n",
        e->versao, e->estrategia, MB_KERNEL, mb_nome_caso(cfg->caso), e->processos,
        cfg->width, cfg->height, cfg->max_iter,
        cfg->real_a, cfg->real_b, cfg->imag_a, cfg->imag_b, e->total_s,
        cmin, csoma / e->processos, cmax,
        gmin, gsoma / e->processos, gmax, e->escrita_s, mb_fbc(cmin, cmax),
        wmin, (double)wsoma / e->processos, wmax, wsoma, e->resolucao_relogio_s,
        cfg->estrategia == MB_CICLICA ? cfg->chunk : 0, r[0].montagem_s);
    if (!fechar_saida(arquivo, erro, erro_cap)) return 0;

    arquivo = abrir_saida(cfg, "_ranks.csv", "w", erro, erro_cap);
    if (!arquivo) return 0;
    fprintf(arquivo, "rank,primeira_linha,linhas,pixels,trabalho_iteracoes,"
                     "tempo_calculo_s,tempo_coleta_s,tempo_total_local_s,tempo_montagem_s,processador\n");
    for (int p = 0; p < e->processos; ++p) {
        fprintf(arquivo, "%d,%d,%d,%" PRIu64 ",%" PRIu64 ",%.9f,%.9f,%.9f,%.9f,",
                r[p].rank, r[p].primeira_linha, r[p].linhas,
                (uint64_t)r[p].linhas * (uint64_t)cfg->width, r[p].trabalho,
                r[p].calculo_s, r[p].coleta_s, r[p].total_s, r[p].montagem_s);
        campo_csv(arquivo, r[p].processador);
        fputc('\n', arquivo);
    }
    if (!fechar_saida(arquivo, erro, erro_cap)) return 0;

    arquivo = abrir_saida(cfg, "_ambiente.txt", "w", erro, erro_cap);
    if (!arquivo) return 0;
    fprintf(arquivo, "kernel=%s\nponteiros_bits=%u\nint32_bytes=%u\n",
            MB_KERNEL, (unsigned)(sizeof(void *) * CHAR_BIT), (unsigned)sizeof(int32_t));
#if defined(_MSC_VER)
    fprintf(arquivo, "compilador=MSVC %d\n", _MSC_FULL_VER);
#elif defined(__VERSION__)
    fprintf(arquivo, "compilador=%s\n", __VERSION__);
#else
    fprintf(arquivo, "compilador=desconhecido\n");
#endif
    fprintf(arquivo, "mpi=%s\nresolucao_relogio_s=%.17g\n",
            e->biblioteca_mpi, e->resolucao_relogio_s);
    if (strcmp(e->versao, "mpi") == 0) {
        fprintf(arquivo,
            "tempo_total=calculo+coleta+montagem+espera_final; setup e escrita excluidos\n"
            "setup=leitura de argumentos, broadcast de parametros, alocacao e barreira inicial\n"
            "coleta=duracao local de MPI_Gatherv, incluindo espera; nao e tempo puro de rede\n"
            "montagem=reordenacao das linhas no root; zero para blocos\n"
            "distribuicao=ciclica: dono da linha y = (y/chunk) %% processos; blocos: faixas contiguas\n"
            "primeira_linha=primeira linha global atribuida ao rank; -1 para rank vazio\n");
    } else {
        fprintf(arquivo,
            "tempo_total=calculo sequencial; argumentos, alocacao e escrita excluidos\n"
            "coleta=zero; versao sequencial nao comunica nem executa barreiras MPI\n");
    }
    fprintf(arquivo,
        "fbc=(max_calculo-min_calculo)/max_calculo; inclui todos os ranks\n"
        "escrita=binario e PPM opcional; CSV e metadados excluidos\n"
        "referencia_professor=pendente; igualdade MPI/serial nao basta para aprova-la\n"
        "ambiente_completo=registrar hardware, SO, flags, comando, binding e condicoes na bateria\n");
    return fechar_saida(arquivo, erro, erro_cap);
}


/* ===== Programa paralelo MPI ===== */


#include <mpi.h>
#include <stdlib.h>
#include <string.h>

/* Faixas contiguas ou blocos de linhas distribuidos ciclicamente. */
static int meu_rank = 0;

static void verificar_mpi(int codigo, const char *operacao)
{
    if (codigo != MPI_SUCCESS) {
        char mensagem[MPI_MAX_ERROR_STRING];
        int comprimento = 0;
        MPI_Error_string(codigo, mensagem, &comprimento);
        fprintf(stderr, "Rank %d: erro em %s: %.*s\n",
                meu_rank, operacao, comprimento, mensagem);
        MPI_Abort(MPI_COMM_WORLD, codigo);
        exit(EXIT_FAILURE);
    }
}

#define MPI_VERIFICAR(chamada) verificar_mpi((chamada), #chamada)

static void distribuir_configuracao(MbConfig *cfg)
{
    /* Tipos basicos, como nos exemplos da aula: nao transmitir structs cruas. */
    int inteiros[7] = {cfg->width, cfg->height, cfg->max_iter, cfg->caso, cfg->ppm,
                       cfg->estrategia, cfg->chunk};
    double limites[4] = {cfg->real_a, cfg->real_b, cfg->imag_a, cfg->imag_b};
    MPI_VERIFICAR(MPI_Bcast(inteiros, 7, MPI_INT, 0, MPI_COMM_WORLD));
    MPI_VERIFICAR(MPI_Bcast(limites, 4, MPI_DOUBLE, 0, MPI_COMM_WORLD));
    cfg->width = inteiros[0];
    cfg->height = inteiros[1];
    cfg->max_iter = inteiros[2];
    cfg->caso = inteiros[3];
    cfg->ppm = inteiros[4];
    cfg->estrategia = inteiros[5];
    cfg->chunk = inteiros[6];
    cfg->real_a = limites[0];
    cfg->real_b = limites[1];
    cfg->imag_a = limites[2];
    cfg->imag_b = limites[3];
    /* O prefixo de saida so e utilizado pelo root. */
}

int main(int argc, char **argv)
{
    MbConfig cfg;
    int linhas_locais;
    MbExecucao execucao = {0};
    MbMetricasRank *metricas = NULL;
    int processos, estado = 0, resultado = EXIT_FAILURE;
    int falha_local, alguma_falha, tamanho_nome, tamanho_versao;
    int *contagens = NULL, *deslocamentos = NULL;
    size_t total_pixels, pixels_locais;
    int32_t *imagem_local = NULL, *imagem_global = NULL, *recebido = NULL;
    uint64_t trabalho_local = 0, *trabalhos = NULL;
    double tempos_local[4] = {0.0, 0.0, 0.0, 0.0}, *tempos = NULL;
    double inicio_total, inicio_coleta, tempo_total = 0.0;
    char erro[1024] = {0};
    char nome_mpi[MPI_MAX_PROCESSOR_NAME + 1] = {0};
    char nome_local[MB_NOME_MAX] = {0}, *nomes = NULL;
    char versao_mpi[MPI_MAX_LIBRARY_VERSION_STRING + 1] = {0};

    if (MPI_Init(&argc, &argv) != MPI_SUCCESS) {
        fprintf(stderr, "Nao foi possivel inicializar MPI.\n");
        return EXIT_FAILURE;
    }
    MPI_VERIFICAR(MPI_Comm_set_errhandler(MPI_COMM_WORLD, MPI_ERRORS_RETURN));
    MPI_VERIFICAR(MPI_Comm_rank(MPI_COMM_WORLD, &meu_rank));
    MPI_VERIFICAR(MPI_Comm_size(MPI_COMM_WORLD, &processos));
    mb_config_padrao(&cfg, "mandelbrot_mpi");

    if (meu_rank == 0) {
        estado = mb_ler_argumentos(argc, argv, &cfg, erro, sizeof(erro));
        if (estado == 1) mb_ajuda(stdout, argv[0]);
        else if (estado < 0) fprintf(stderr, "%s\n", erro);
    }
    /* Todos seguem o mesmo caminho, inclusive em --help ou argumento invalido. */
    MPI_VERIFICAR(MPI_Bcast(&estado, 1, MPI_INT, 0, MPI_COMM_WORLD));
    if (estado != 0) {
        if (MPI_Finalize() != MPI_SUCCESS) return EXIT_FAILURE;
        return estado == 1 ? EXIT_SUCCESS : EXIT_FAILURE;
    }
    distribuir_configuracao(&cfg);
    if (!mb_total_pixels(&cfg, &total_pixels)) {
        fprintf(stderr, "Rank %d: dimensoes invalidas.\n", meu_rank);
        MPI_Abort(MPI_COMM_WORLD, EXIT_FAILURE);
        return EXIT_FAILURE;
    }

    linhas_locais = mb_quantidade_linhas(&cfg, processos, meu_rank);
    pixels_locais = (size_t)linhas_locais * (size_t)cfg.width;
    imagem_local = mb_alocar_pixels(pixels_locais);
    falha_local = imagem_local == NULL;
    if (meu_rank == 0) {
        imagem_global = mb_alocar_pixels(total_pixels);
        if (cfg.estrategia == MB_CICLICA) recebido = mb_alocar_pixels(total_pixels);
        contagens = (int *)calloc((size_t)processos, sizeof(*contagens));
        deslocamentos = (int *)calloc((size_t)processos, sizeof(*deslocamentos));
        metricas = (MbMetricasRank *)calloc((size_t)processos, sizeof(*metricas));
        tempos = (double *)calloc((size_t)processos, 4 * sizeof(*tempos));
        trabalhos = (uint64_t *)calloc((size_t)processos, sizeof(*trabalhos));
        nomes = (char *)calloc((size_t)processos, MB_NOME_MAX);
        if (!imagem_global || !contagens || !deslocamentos || !metricas ||
            !tempos || !trabalhos || !nomes) falha_local = 1;
        if (cfg.estrategia == MB_CICLICA && !recebido) falha_local = 1;
    }
    MPI_VERIFICAR(MPI_Allreduce(&falha_local, &alguma_falha, 1, MPI_INT,
                               MPI_MAX, MPI_COMM_WORLD));
    if (alguma_falha) {
        if (meu_rank == 0) fprintf(stderr, "Memoria insuficiente em um ou mais processos.\n");
        goto finalizar;
    }
    if (meu_rank == 0) {
        int deslocamento = 0;
        for (int p = 0; p < processos; ++p) {
            /* Produto total previamente limitado a INT_MAX. */
            contagens[p] = mb_quantidade_linhas(&cfg, processos, p) * cfg.width;
            deslocamentos[p] = deslocamento;
            deslocamento += contagens[p];
        }
    }
    MPI_VERIFICAR(MPI_Get_processor_name(nome_mpi, &tamanho_nome));
    nome_mpi[tamanho_nome] = '\0';
    snprintf(nome_local, sizeof(nome_local), "%s", nome_mpi);
    MPI_VERIFICAR(MPI_Get_library_version(versao_mpi, &tamanho_versao));
    versao_mpi[tamanho_versao] = '\0';

    /* Setup e barreira inicial ficam fora do tempo de geracao. */
    MPI_VERIFICAR(MPI_Barrier(MPI_COMM_WORLD));
    inicio_total = MPI_Wtime();
    trabalho_local = mb_calcular_parte(&cfg, processos, meu_rank, imagem_local);
    tempos_local[0] = linhas_locais ? MPI_Wtime() - inicio_total : 0.0;

    /* Sem barreira intermediaria: preserva a espera real de quem termina cedo. */
    inicio_coleta = MPI_Wtime();
    MPI_VERIFICAR(MPI_Gatherv(imagem_local, (int)pixels_locais, MPI_INT32_T,
                             cfg.estrategia == MB_CICLICA ? recebido : imagem_global,
                             contagens, deslocamentos, MPI_INT32_T,
                             0, MPI_COMM_WORLD));
    tempos_local[1] = MPI_Wtime() - inicio_coleta;
    if (meu_rank == 0 && cfg.estrategia == MB_CICLICA) {
        double inicio_montagem = MPI_Wtime();
        mb_montar_imagem(&cfg, processos, recebido, imagem_global);
        tempos_local[2] = MPI_Wtime() - inicio_montagem;
    }
    MPI_VERIFICAR(MPI_Barrier(MPI_COMM_WORLD));
    tempos_local[3] = MPI_Wtime() - inicio_total;

    /* Agregacao de metricas excluida do intervalo medido. Nao subtrair relogios
       de ranks diferentes: reduzimos apenas duracoes medidas localmente. */
    MPI_VERIFICAR(MPI_Reduce(&tempos_local[3], &tempo_total, 1, MPI_DOUBLE,
                            MPI_MAX, 0, MPI_COMM_WORLD));
    MPI_VERIFICAR(MPI_Gather(tempos_local, 4, MPI_DOUBLE, tempos, 4, MPI_DOUBLE,
                            0, MPI_COMM_WORLD));
    MPI_VERIFICAR(MPI_Gather(&trabalho_local, 1, MPI_UINT64_T, trabalhos, 1,
                            MPI_UINT64_T, 0, MPI_COMM_WORLD));
    MPI_VERIFICAR(MPI_Gather(nome_local, MB_NOME_MAX, MPI_CHAR, nomes, MB_NOME_MAX,
                            MPI_CHAR, 0, MPI_COMM_WORLD));

    resultado = EXIT_SUCCESS;
    if (meu_rank == 0) {
        double inicio_escrita;
        int ok;
        for (int p = 0; p < processos; ++p) {
            metricas[p].rank = p;
            metricas[p].primeira_linha = mb_linha_global(&cfg, processos, p, 0);
            metricas[p].linhas = mb_quantidade_linhas(&cfg, processos, p);
            metricas[p].trabalho = trabalhos[p];
            metricas[p].calculo_s = tempos[4 * (size_t)p];
            metricas[p].coleta_s = tempos[4 * (size_t)p + 1];
            metricas[p].montagem_s = tempos[4 * (size_t)p + 2];
            metricas[p].total_s = tempos[4 * (size_t)p + 3];
            memcpy(metricas[p].processador, nomes + (size_t)p * MB_NOME_MAX, MB_NOME_MAX);
        }
        inicio_escrita = MPI_Wtime();
        ok = mb_salvar_binario(&cfg, imagem_global, erro, sizeof(erro));
        if (ok && cfg.ppm) ok = mb_salvar_ppm(&cfg, imagem_global, erro, sizeof(erro));
        execucao.escrita_s = MPI_Wtime() - inicio_escrita;
        execucao.versao = "mpi";
        execucao.estrategia = mb_nome_estrategia(cfg.estrategia);
        execucao.biblioteca_mpi = versao_mpi;
        execucao.processos = processos;
        execucao.total_s = tempo_total;
        execucao.resolucao_relogio_s = MPI_Wtick();
        execucao.ranks = metricas;
        if (ok) ok = mb_salvar_metricas(&cfg, &execucao, erro, sizeof(erro));
        if (!ok) {
            fprintf(stderr, "%s\n", erro);
            resultado = EXIT_FAILURE;
        } else {
            printf("MPI %s | %s | %dx%d | %d processos | total %.6f s | escrita %.6f s\n",
                   execucao.estrategia, mb_nome_caso(cfg.caso), cfg.width, cfg.height, processos,
                   execucao.total_s, execucao.escrita_s);
        }
    }
    /* Uma falha de escrita no root faz a execucao inteira retornar erro. */
    MPI_VERIFICAR(MPI_Bcast(&resultado, 1, MPI_INT, 0, MPI_COMM_WORLD));

finalizar:
    free(nomes);
    free(trabalhos);
    free(tempos);
    free(metricas);
    free(deslocamentos);
    free(contagens);
    free(recebido);
    free(imagem_global);
    free(imagem_local);
    if (MPI_Finalize() != MPI_SUCCESS) return EXIT_FAILURE;
    return resultado;
}