"""Pipeline ETL reprodutível para os Microdados do ENADE 2018 (INEP).

Processa o arquivo bruto ``microdados_enade_2018.txt`` (548.127 registros) e gera
duas tabelas leves em ``data/processed/`` prontas para análise e versionamento:

1. ``enade_2018_resumo_cursos.csv``: estatísticas agregadas por área de
   enquadramento (``CO_GRUPO``) e categoria administrativa (Pública vs. Privada).
2. ``enade_2018_economia.csv``: microdados completos do curso de Ciências
   Econômicas (``CO_GRUPO == 13``, 9.582 estudantes) com notas convertidas para
   formato numérico e atributos socioeconômicos selecionados.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
RAW_TMP_DIR = PROJECT_ROOT / "_tmp_raw"

RAW_RAR_URL = (
    "https://raw.githubusercontent.com/mmhasega/economia-ufpr-enade-2018/"
    "master/dados/microdados_enade_2018.rar"
)
WAYBACK_ZIP_URL = (
    "https://web.archive.org/web/20200513083143id_/"
    "http://download.inep.gov.br/microdados/Enade_Microdados/microdados_enade_2018.zip"
)

DICT_CURSOS: dict[int, str] = {
    1: "ADMINISTRAÇÃO",
    2: "DIREITO",
    13: "CIÊNCIAS ECONÔMICAS",
    18: "PSICOLOGIA",
    22: "CIÊNCIAS CONTÁBEIS",
    26: "DESIGN",
    29: "TURISMO",
    38: "SERVIÇO SOCIAL",
    67: "SECRETARIADO EXECUTIVO",
    81: "RELAÇÕES INTERNACIONAIS",
    83: "TECNOLOGIA EM DESIGN DE MODA",
    84: "TECNOLOGIA EM MARKETING",
    85: "TECNOLOGIA EM PROCESSOS GERENCIAIS",
    86: "TECNOLOGIA EM GESTÃO DE RECURSOS HUMANOS",
    87: "TECNOLOGIA EM GESTÃO FINANCEIRA",
    88: "TECNOLOGIA EM GASTRONOMIA",
    93: "TECNOLOGIA EM GESTÃO COMERCIAL",
    94: "TECNOLOGIA EM LOGÍSTICA",
    100: "ADMINISTRAÇÃO PÚBLICA",
    101: "TEOLOGIA",
    102: "TECNOLOGIA EM COMÉRCIO EXTERIOR",
    103: "TECNOLOGIA EM DESIGN DE INTERIORES",
    104: "TECNOLOGIA EM DESIGN GRÁFICO",
    105: "TECNOLOGIA EM GESTÃO DA QUALIDADE",
    106: "TECNOLOGIA EM GESTÃO PÚBLICA",
    803: "COMUNICAÇÃO SOCIAL - JORNALISMO",
    804: "COMUNICAÇÃO SOCIAL - PUBLICIDADE E PROPAGANDA",
}

DICT_CATEGAD: dict[int, str] = {
    93: "Pública",
    115: "Pública",
    116: "Pública",
    118: "Privada",
    120: "Privada",
    121: "Privada",
    10001: "Pública",
    10002: "Pública",
    10003: "Pública",
    10005: "Privada",
    10006: "Privada",
    10007: "Privada",
    10008: "Privada",
    10009: "Privada",
    17634: "Pública",
}

DICT_ESFERA: dict[int, str] = {
    93: "Pública Federal",
    10002: "Pública Federal",
    115: "Pública Estadual",
    10001: "Pública Estadual",
    116: "Pública Municipal",
    10003: "Pública Municipal",
    17634: "Pública Municipal",
    120: "Privada sem Fins Lucrativos",
    121: "Privada sem Fins Lucrativos",
    10007: "Privada sem Fins Lucrativos",
    10008: "Privada sem Fins Lucrativos",
    10009: "Privada sem Fins Lucrativos",
    118: "Privada com Fins Lucrativos",
    10005: "Privada com Fins Lucrativos",
    10006: "Privada com Fins Lucrativos",
}

DICT_REGIAO: dict[int, str] = {
    1: "Norte",
    2: "Nordeste",
    3: "Sudeste",
    4: "Sul",
    5: "Centro-Oeste",
}

DICT_MODALIDADE: dict[int, str] = {
    1: "Presencial",
    2: "EaD",
}

SCORE_COLS = [
    "NT_GER",
    "NT_FG",
    "NT_CE",
    "NT_OBJ_FG",
    "NT_DIS_FG",
    "NT_OBJ_CE",
    "NT_DIS_CE",
]

ECONOMIA_COLS = [
    "NU_ANO",
    "CO_IES",
    "CO_CATEGAD",
    "CO_ORGACAD",
    "CO_GRUPO",
    "CO_CURSO",
    "CO_MODALIDADE",
    "CO_MUNIC_CURSO",
    "CO_UF_CURSO",
    "CO_REGIAO_CURSO",
    "CO_TURNO_GRADUACAO",
    "NU_IDADE",
    "TP_SEXO",
    "TP_PRES",
    "TP_PR_GER",
    *SCORE_COLS,
    "QE_I01",
    "QE_I02",
    "QE_I04",
    "QE_I05",
    "QE_I06",
    "QE_I07",
    "QE_I08",
    "QE_I09",
    "QE_I10",
    "QE_I11",
    "QE_I15",
    "QE_I17",
    "QE_I18",
    "QE_I21",
    "QE_I22",
    "QE_I23",
]


def _find_unrar() -> str | None:
    """Localiza o executável ``UnRAR`` no sistema."""
    for candidate in (
        shutil.which("unrar"),
        r"C:\Program Files\WinRAR\UnRAR.exe",
        r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
    ):
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def _download_raw_txt(dest_dir: Path) -> Path:
    """Baixa e extrai ``microdados_enade_2018.txt`` quando não fornecido localmente."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    txt_path = dest_dir / "microdados_enade_2018.txt"
    if txt_path.exists():
        return txt_path

    unrar_bin = _find_unrar()
    rar_path = dest_dir / "microdados_enade_2018.rar"
    if unrar_bin:
        print(f"Baixando arquivo bruto de {RAW_RAR_URL}...")
        subprocess.run(
            ["curl.exe" if shutil.which("curl.exe") else "curl", "-L", "-o", str(rar_path), RAW_RAR_URL],
            check=True,
        )
        subprocess.run(
            [unrar_bin, "e", "-y", str(rar_path), "microdados_enade_2018.txt", str(dest_dir) + "\\"],
            check=True,
        )
        if txt_path.exists():
            return txt_path

    zip_path = dest_dir / "microdados_enade_2018.zip"
    print(f"Baixando fallback ZIP de {WAYBACK_ZIP_URL}...")
    req = urllib.request.Request(WAYBACK_ZIP_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(zip_path, "wb") as out:
        shutil.copyfileobj(resp, out)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.endswith("microdados_enade_2018.txt"):
                with zf.open(member) as src, open(txt_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                break
    if not txt_path.exists():
        raise FileNotFoundError("Não foi possível extrair microdados_enade_2018.txt.")
    return txt_path


def _parse_br_float(series: pd.Series) -> pd.Series:
    """Converte strings numéricas com vírgula decimal para float."""
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    return pd.to_numeric(series.astype(str).str.replace(",", ".", regex=False), errors="coerce")


def build_resumo_cursos(df_all: pd.DataFrame) -> pd.DataFrame:
    """Agrega estatísticas nacionais do ENADE 2018 por curso e categoria administrativa."""
    base = df_all[["CO_GRUPO", "CO_CATEGAD", "TP_PRES", "NT_GER"]].copy()
    base["NT_GER"] = _parse_br_float(base["NT_GER"])
    base["curso_nome"] = base["CO_GRUPO"].map(DICT_CURSOS)
    base["categoria_administrativa"] = base["CO_CATEGAD"].map(DICT_CATEGAD)
    base["presente_nota_valida"] = base["NT_GER"].notna().astype(int)
    base["presente_tp555"] = (base["TP_PRES"] == 555).astype(int)

    resumo = (
        base.groupby(["CO_GRUPO", "curso_nome", "categoria_administrativa"], dropna=False)
        .agg(
            total_inscritos=("CO_GRUPO", "size"),
            total_presentes=("presente_nota_valida", "sum"),
            total_presentes_tp555=("presente_tp555", "sum"),
            media_nt_ger=("NT_GER", "mean"),
            mediana_nt_ger=("NT_GER", "median"),
            desvio_padrao_nt_ger=("NT_GER", "std"),
            q25_nt_ger=("NT_GER", lambda s: s.quantile(0.25)),
            q75_nt_ger=("NT_GER", lambda s: s.quantile(0.75)),
        )
        .reset_index()
    )
    resumo["taxa_presenca_pct"] = (resumo["total_presentes"] / resumo["total_inscritos"] * 100).round(2)
    numeric_cols = [
        "media_nt_ger",
        "mediana_nt_ger",
        "desvio_padrao_nt_ger",
        "q25_nt_ger",
        "q75_nt_ger",
    ]
    resumo[numeric_cols] = resumo[numeric_cols].round(4)
    return resumo.sort_values(["total_inscritos", "CO_GRUPO"], ascending=[False, True]).reset_index(drop=True)


def build_economia_dataset(df_all: pd.DataFrame) -> pd.DataFrame:
    """Filtra estudantes de Ciências Econômicas e padroniza notas e rótulos institucionais."""
    econ = df_all.loc[df_all["CO_GRUPO"] == 13, ECONOMIA_COLS].copy()
    for col in SCORE_COLS:
        econ[col] = _parse_br_float(econ[col])

    econ["categoria_administrativa"] = econ["CO_CATEGAD"].map(DICT_CATEGAD)
    econ["esfera_administrativa"] = econ["CO_CATEGAD"].map(DICT_ESFERA)
    econ["modalidade_ensino"] = econ["CO_MODALIDADE"].map(DICT_MODALIDADE)
    econ["regiao_nome"] = econ["CO_REGIAO_CURSO"].map(DICT_REGIAO)
    return econ.reset_index(drop=True)


def run_etl(raw_path: Path | None = None, keep_raw: bool = False) -> None:
    """Executa o pipeline completo e salva os CSVs em ``data/processed/``."""
    downloaded_tmp = False
    if raw_path is None:
        candidate = RAW_TMP_DIR / "microdados_enade_2018.txt"
        if candidate.exists():
            raw_path = candidate
        else:
            raw_path = _download_raw_txt(RAW_TMP_DIR)
            downloaded_tmp = True

    print(f"Lendo microdados brutos de: {raw_path}")
    df_all = pd.read_csv(
        raw_path,
        sep=";",
        encoding="latin-1",
        usecols=sorted(set(ECONOMIA_COLS)),
        low_memory=False,
    )
    print(f"Total de registros carregados (ENADE 2018 completo): {len(df_all):,}".replace(",", "."))

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    resumo = build_resumo_cursos(df_all)
    resumo_path = PROCESSED_DIR / "enade_2018_resumo_cursos.csv"
    resumo.to_csv(resumo_path, index=False, encoding="utf-8")

    econ = build_economia_dataset(df_all)
    econ_path = PROCESSED_DIR / "enade_2018_economia.csv"
    econ.to_csv(econ_path, index=False, encoding="utf-8")

    modelo_vars = ["NT_GER", "QE_I04", "QE_I05", "QE_I10", "QE_I17", "QE_I23"]
    n_presentes_econ = int(econ["NT_GER"].notna().sum())
    n_modelo_econ = int(econ.dropna(subset=modelo_vars).shape[0])

    print(f"Salvo {resumo_path} ({len(resumo)} linhas, {resumo['total_inscritos'].sum():,} alunos)")
    print(f"Salvo {econ_path} ({len(econ):,} inscritos em Economia)")
    print(f"Economia com NT_GER válida: {n_presentes_econ:,}")
    print(f"Economia com respostas completas nas 5 variáveis do modelo: {n_modelo_econ:,}")

    if downloaded_tmp and not keep_raw and RAW_TMP_DIR.exists():
        shutil.rmtree(RAW_TMP_DIR)
        print("Arquivos brutos temporários removidos.")


def main() -> None:
    parser = argparse.ArgumentParser(description="ETL dos Microdados ENADE 2018 (Ciências Econômicas).")
    parser.add_argument("--input", type=Path, default=None, help="Caminho opcional para microdados_enade_2018.txt")
    parser.add_argument("--keep-raw", action="store_true", help="Mantém os arquivos brutos baixados em _tmp_raw/")
    args = parser.parse_args()
    run_etl(raw_path=args.input, keep_raw=args.keep_raw)


if __name__ == "__main__":
    main()
