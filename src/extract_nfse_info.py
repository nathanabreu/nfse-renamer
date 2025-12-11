import re
import pdfplumber

REGEX_CNPJ = r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"
REGEX_NFSE = r"(?i)Número da Nota\s*[\r\n ]*([0-9]{1,10})"
REGEX_RPS = r"RPS Nº\s*([0-9]+)"
REGEX_SERIE = r"Série\s*([0-9]+)"

def extract_nfse_info(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join([p.extract_text() or "" for p in pdf.pages])

    cnpj = re.search(REGEX_CNPJ, full_text)
    if not cnpj:
        raise ValueError("CNPJ não encontrado.")
    cnpj = re.sub(r"\D", "", cnpj.group(0))

    nfse = re.search(REGEX_NFSE, full_text)
    if not nfse:
        raise ValueError("Número da NFSe não encontrado.")
    nfse_num = str(int(nfse.group(1)))

    rps = re.search(REGEX_RPS, full_text)
    if not rps:
        raise ValueError("Número RPS não encontrado.")
    rps_num = rps.group(1)

    serie = re.search(REGEX_SERIE, full_text)
    if not serie:
        raise ValueError("Série não encontrada.")
    serie_num = serie.group(1)

    # Garante que o prefixo "nfse" seja sempre minúsculo
    return f"nfse_{cnpj}_{rps_num}_{nfse_num}_{serie_num}".lower()

