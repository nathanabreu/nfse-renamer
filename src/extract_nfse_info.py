import re
import pdfplumber

# PdfminerException não está disponível diretamente no pdfplumber
# Criamos uma classe dummy para verificação de tipo de erro
class PdfminerException(Exception):
    """Exceção do pdfminer para tratamento de erros específicos do PDF."""
    pass

REGEX_CNPJ = r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"
REGEX_NFSE = r"(?i)Número da Nota\s*[\r\n ]*([0-9]{1,10})"
REGEX_RPS = r"RPS Nº\s*([0-9]+)"
REGEX_SERIE = r"(?i)Série\s*([A-Za-z0-9\-_]+)"

def extract_nfse_info(pdf_path):
    """
    Extrai informações de NFSe do PDF.
    Trata erros específicos do pdfplumber.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join([p.extract_text() or "" for p in pdf.pages])
    except PdfminerException as e:
        # Propaga PdfminerException diretamente para melhor tratamento no código chamador
        raise
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        
        # Trata erros específicos do pdfplumber/pdfminer
        if "No /Root object" in error_msg or "/Root" in error_msg or "Root" in error_msg:
            raise ValueError(f"PDF não pode ser lido pelo pdfplumber (estrutura não padrão): {error_msg}. O PDF pode estar corrompido ou ter formato não suportado.")
        elif "PdfminerException" in error_type or "pdfminer" in error_msg.lower():
            # Se for PdfminerException mas não foi capturado acima, propaga como PdfminerException
            raise PdfminerException(error_msg)
        else:
            raise ValueError(f"Erro ao abrir PDF: {error_type}: {error_msg}")

    
    # Verifica se conseguiu extrair texto
    if not full_text or len(full_text.strip()) < 50:
        raise ValueError("PDF não contém texto legível ou está vazio (texto extraído muito curto)")
    
    cnpj = re.search(REGEX_CNPJ, full_text)
    if not cnpj:
        raise ValueError("CNPJ não encontrado no PDF.")
    cnpj = re.sub(r"\D", "", cnpj.group(0))

    nfse = re.search(REGEX_NFSE, full_text)
    if not nfse:
        raise ValueError("Número da NFSe não encontrado no PDF.")
    nfse_num = str(int(nfse.group(1)))

    rps = re.search(REGEX_RPS, full_text)
    if not rps:
        raise ValueError("Número RPS não encontrado no PDF.")
    rps_num = rps.group(1)

    serie = re.search(REGEX_SERIE, full_text)
    if not serie:
        raise ValueError("Série não encontrada no PDF.")
    serie_num = serie.group(1)

    # Regra especial: quando CNPJ for 02886427001306, série deve ser maiúscula
    if cnpj == "02886427001306":
        serie_num = serie_num.upper()
        return f"nfse_{cnpj}_{rps_num}_{nfse_num}_{serie_num}".lower().rsplit('_', 1)[0] + '_' + serie_num
    
    # Garante que o prefixo "nfse" seja sempre minúsculo
    return f"nfse_{cnpj}_{rps_num}_{nfse_num}_{serie_num}".lower()

