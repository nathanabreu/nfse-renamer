#!/usr/bin/env python3
"""
NFSe Renamer Service - Serviço principal
"""
import os
import shutil
import logging
import signal
import sys
import stat
import time
from time import sleep
import ftplib
from ftplib import FTP, FTP_TLS
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from .extract_nfse_info import extract_nfse_info

CONFIG_FILE = "/opt/nfse-renamer/config.env"
CONFIG = {}
PROCESSING_FILES = set()  # Controla arquivos em processamento

def load_config():
    """Carrega configurações do arquivo config.env"""
    global CONFIG
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {CONFIG_FILE}")
    
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                CONFIG[k.strip()] = v.strip().strip('"').strip("'")
    
    # Valores padrão se não especificados
    CONFIG.setdefault("INPUT_DIR", "/opt/nfse-renamer/files/inbound")
    CONFIG.setdefault("OUTPUT_DIR", "/opt/nfse-renamer/files/processed")
    CONFIG.setdefault("REJECT_DIR", "/opt/nfse-renamer/files/reject")
    CONFIG.setdefault("LOG_FILE", "/opt/nfse-renamer/logs/nfse_renamer.log")
    CONFIG.setdefault("POLLING_INTERVAL", "5")  # segundos
    CONFIG.setdefault("USE_POLLING", "false")  # usar watchdog por padrão
    CONFIG.setdefault("MAX_RETRIES", "3")
    CONFIG.setdefault("RETRY_DELAY", "2")  # segundos
    CONFIG.setdefault("PROCESS_TIMEOUT", "60")  # segundos
    CONFIG.setdefault("FILE_PERMISSIONS", "644")  # permissões em octal
    CONFIG.setdefault("DIR_PERMISSIONS", "755")  # permissões de diretórios em octal
    CONFIG.setdefault("FIX_PERMISSIONS_ON_CYCLE", "true")  # ajustar permissões a cada ciclo
    CONFIG.setdefault("RENAME_IN_PLACE", "false")  # renomear na própria pasta
    CONFIG.setdefault("USE_FTP", "false")  # usar FTP como destino
    CONFIG.setdefault("FTP_HOST", "")
    CONFIG.setdefault("FTP_PORT", "21")
    CONFIG.setdefault("FTP_USER", "")
    CONFIG.setdefault("FTP_PASSWORD", "")
    CONFIG.setdefault("FTP_PATH", "/")
    CONFIG.setdefault("FTP_PASSIVE", "true")
    CONFIG.setdefault("FTP_TIMEOUT", "30")
    CONFIG.setdefault("FTP_USE_TLS", "false")
    
    # Verifica modo RENAME_IN_PLACE
    rename_in_place = CONFIG.get("RENAME_IN_PLACE", "false").lower() in ("true", "1", "yes")
    
    # INPUT_DIR sempre é necessário
    dirs_to_manage = ["INPUT_DIR"]
    
    # REJECT_DIR sempre é necessário (arquivos com erro são movidos para reject mesmo em RENAME_IN_PLACE)
    # OUTPUT_DIR só é necessário se não estiver em modo RENAME_IN_PLACE
    dirs_to_manage.append("REJECT_DIR")
    if not rename_in_place:
        dirs_to_manage.append("OUTPUT_DIR")
    
    # Criar diretórios se não existirem e ajustar permissões
    for dir_key in dirs_to_manage:
        dir_path = CONFIG[dir_key]
        
        # Verifica se diretório já existe
        if not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
                # Não usar logging aqui, ainda não está configurado
            except Exception as e:
                print(f"AVISO: Erro ao criar diretório {dir_path}: {e}")
                continue
        
        # Ajusta permissões do diretório (seja criado agora ou já existente)
        try:
            dir_permissions = int(CONFIG["DIR_PERMISSIONS"], 8)
            os.chmod(dir_path, dir_permissions)
        except Exception as e:
            print(f"AVISO: Erro ao ajustar permissões do diretório {dir_path}: {e}")
    
    # Criar diretório de logs (não usar logging aqui, ainda não está configurado)
    log_dir = os.path.dirname(CONFIG["LOG_FILE"])
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            print(f"ERRO: Falha ao criar diretório de logs {log_dir}: {e}")
            raise

def setup_logging():
    """Configura sistema de logging - sempre escreve no arquivo configurado"""
    # Garante que o diretório de logs existe
    log_dir = os.path.dirname(CONFIG["LOG_FILE"])
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            print(f"ERRO: Falha ao criar diretório de logs {log_dir}: {e}")
            sys.exit(1)
    
    # Remove handlers existentes para evitar duplicação
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()  # Fecha handlers antigos adequadamente
    
    # Configura formato
    log_format = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    
    # Handler para arquivo - SEMPRE adicionado, mesmo quando rodando como systemd
    try:
        file_handler = logging.FileHandler(CONFIG["LOG_FILE"], mode='a', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(log_format)
        # Força flush imediato para garantir que logs não sejam perdidos
        file_handler.flush()
        root_logger.addHandler(file_handler)
        
        # Testa se consegue escrever no arquivo
        logging.info("=" * 60)
        logging.info("Sistema de logging inicializado")
        logging.info(f"Logs serão salvos em: {CONFIG['LOG_FILE']}")
        # Força flush após teste
        file_handler.flush()
    except Exception as e:
        print(f"ERRO: Falha ao configurar arquivo de log {CONFIG['LOG_FILE']}: {e}")
        sys.exit(1)
    
    # Handler para console - adiciona também quando rodando como systemd
    # Isso permite que logs apareçam no journal do systemd E no arquivo
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)
    
    root_logger.setLevel(logging.INFO)
    
    # Log adicional para confirmar que está funcionando
    logging.info("Handler de arquivo configurado e ativo")
    
    # Força flush inicial
    for handler in root_logger.handlers:
        if hasattr(handler, 'flush'):
            handler.flush()

def flush_logs():
    """Força flush de todos os handlers de log para garantir escrita no arquivo"""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if hasattr(handler, 'flush'):
            try:
                handler.flush()
            except Exception:
                pass  # Ignora erros de flush

def wait_for_file_ready(file_path, max_wait=10):
    """Aguarda arquivo estar completamente escrito e disponível"""
    for _ in range(max_wait):
        try:
            # Verifica se arquivo existe e não está sendo escrito
            if os.path.exists(file_path):
                # Tenta abrir em modo exclusivo
                try:
                    with open(file_path, 'r+b'):
                        return True
                except (IOError, OSError):
                    sleep(0.5)
                    continue
        except Exception:
            sleep(0.5)
    return False

def is_file_locked(file_path):
    """Verifica se arquivo está em uso"""
    try:
        with open(file_path, 'r+b'):
            return False
    except (IOError, OSError):
        return True

def set_file_permissions(file_path):
    """
    Ajusta permissões de um arquivo conforme configuração
    """
    try:
        if not os.path.exists(file_path):
            return False
        
        # Converte permissão de string octal para int
        permissions = int(CONFIG["FILE_PERMISSIONS"], 8)
        os.chmod(file_path, permissions)
        logging.debug(f"Permissões ajustadas para {file_path}: {CONFIG['FILE_PERMISSIONS']}")
        return True
    except Exception as e:
        logging.warning(f"Erro ao ajustar permissões de {file_path}: {e}")
        return False

def fix_permissions_in_directory(directory):
    """
    Ajusta permissões de todos os arquivos PDF em um diretório
    """
    if not os.path.exists(directory):
        return
    
    try:
        fixed_count = 0
        for file in os.listdir(directory):
            file_path = os.path.join(directory, file)
            if os.path.isfile(file_path) and file.lower().endswith(".pdf"):
                if set_file_permissions(file_path):
                    fixed_count += 1
        
        if fixed_count > 0:
            logging.debug(f"Permissões ajustadas para {fixed_count} arquivo(s) em {directory}")
    except Exception as e:
        logging.error(f"Erro ao ajustar permissões em {directory}: {e}")

def set_directory_permissions(directory):
    """
    Ajusta permissões de um diretório conforme configuração
    """
    try:
        if not os.path.exists(directory):
            return False
        
        dir_permissions = int(CONFIG["DIR_PERMISSIONS"], 8)
        os.chmod(directory, dir_permissions)
        logging.debug(f"Permissões do diretório ajustadas: {directory} -> {CONFIG['DIR_PERMISSIONS']}")
        return True
    except Exception as e:
        logging.warning(f"Erro ao ajustar permissões do diretório {directory}: {e}")
        return False

def fix_all_permissions():
    """
    Ajusta permissões de todos os PDFs e diretórios nas pastas de processamento
    """
    if CONFIG.get("FIX_PERMISSIONS_ON_CYCLE", "true").lower() not in ("true", "1", "yes"):
        return
    
    rename_in_place = CONFIG.get("RENAME_IN_PLACE", "false").lower() in ("true", "1", "yes")
    
    # Ajusta permissões dos diretórios (apenas se existirem)
    if os.path.exists(CONFIG["INPUT_DIR"]):
        set_directory_permissions(CONFIG["INPUT_DIR"])
    
    # REJECT_DIR sempre é usado (arquivos com erro são movidos para reject)
    if os.path.exists(CONFIG["REJECT_DIR"]):
        set_directory_permissions(CONFIG["REJECT_DIR"])
        fix_permissions_in_directory(CONFIG["REJECT_DIR"])
    
    # OUTPUT_DIR só é usado se não estiver em modo RENAME_IN_PLACE
    if not rename_in_place:
        if os.path.exists(CONFIG["OUTPUT_DIR"]):
            set_directory_permissions(CONFIG["OUTPUT_DIR"])
            fix_permissions_in_directory(CONFIG["OUTPUT_DIR"])
    else:
        # No modo RENAME_IN_PLACE, ajusta permissões também em INPUT_DIR
        if os.path.exists(CONFIG["INPUT_DIR"]):
            fix_permissions_in_directory(CONFIG["INPUT_DIR"])

def upload_to_ftp(local_file_path, remote_filename):
    """
    Faz upload de arquivo para servidor FTP.
    Suporta FTP anônimo (sem user/password) e autenticado.
    Retorna True se bem-sucedido, False caso contrário.
    """
    try:
        ftp_host = CONFIG.get("FTP_HOST", "").strip()
        ftp_port = int(CONFIG.get("FTP_PORT", "21"))
        ftp_user = CONFIG.get("FTP_USER", "").strip()
        ftp_password = CONFIG.get("FTP_PASSWORD", "").strip()
        ftp_path = CONFIG.get("FTP_PATH", "/").strip()
        ftp_passive = CONFIG.get("FTP_PASSIVE", "true").lower() in ("true", "1", "yes")
        ftp_timeout = int(CONFIG.get("FTP_TIMEOUT", "30"))
        use_tls = CONFIG.get("FTP_USE_TLS", "false").lower() in ("true", "1", "yes")
        
        if not ftp_host:
            logging.error("FTP_HOST não configurado")
            return False
        
        # Conecta ao servidor FTP
        if use_tls:
            ftp = FTP_TLS()
            ftp.connect(ftp_host, ftp_port, timeout=ftp_timeout)
            # Login: usa credenciais se fornecidas, senão tenta anônimo
            if ftp_user:
                ftp.login(ftp_user, ftp_password)
            else:
                ftp.login()  # Login anônimo
            ftp.prot_p()  # Protege a conexão de dados
        else:
            ftp = FTP()
            ftp.connect(ftp_host, ftp_port, timeout=ftp_timeout)
            # Login: usa credenciais se fornecidas, senão tenta anônimo
            if ftp_user:
                ftp.login(ftp_user, ftp_password)
            else:
                ftp.login()  # Login anônimo
        
        # Configura modo passivo
        if ftp_passive:
            ftp.set_pasv(True)
        
        # Navega para o diretório remoto (cria se não existir)
        if ftp_path and ftp_path != "/":
            try:
                ftp.cwd(ftp_path)
            except ftplib.error_perm:
                # Tenta criar o diretório
                try:
                    # Divide o caminho em partes e cria recursivamente
                    path_parts = ftp_path.strip("/").split("/")
                    current_path = ""
                    for part in path_parts:
                        if part:
                            current_path = current_path + "/" + part if current_path else part
                            try:
                                ftp.cwd(current_path)
                            except ftplib.error_perm:
                                try:
                                    ftp.mkd(current_path)
                                    ftp.cwd(current_path)
                                except:
                                    pass
                except:
                    logging.warning(f"Não foi possível criar/acessar diretório FTP: {ftp_path}")
        
        # Faz upload do arquivo
        with open(local_file_path, 'rb') as file:
            ftp.storbinary(f'STOR {remote_filename}', file)
        
        ftp.quit()
        
        # Log informativo sobre tipo de conexão
        auth_type = "autenticado" if ftp_user else "anônimo"
        logging.info(f"Arquivo enviado para FTP ({auth_type}): {ftp_host}{ftp_path}/{remote_filename}")
        return True
        
    except ftplib.error_perm as e:
        logging.error(f"Erro de permissão FTP: {e}")
        return False
    except ftplib.error_temp as e:
        logging.error(f"Erro temporário FTP: {e}")
        return False
    except Exception as e:
        logging.error(f"Erro ao fazer upload FTP: {type(e).__name__}: {e}")
        return False

def should_process_file(filename):
    """
    Verifica se o arquivo deve ser processado.
    Processa apenas arquivos que começam com "NFSE" em maiúsculo.
    """
    if not filename.lower().endswith(".pdf"):
        return False
    
    # Processa apenas arquivos que começam com "NFSE" (maiúsculo)
    # Isso evita reprocessar arquivos já processados (que começam com "nfse" minúsculo)
    return filename.startswith("NFSE_")

def check_if_file_was_processed(original_path):
    """
    Verifica se o arquivo foi processado procurando pelo arquivo renomeado.
    Retorna o caminho do arquivo processado se encontrado, None caso contrário.
    """
    # Obtém informações do arquivo original antes de procurar
    original_size = None
    original_mtime = None
    original_exists = os.path.exists(original_path)
    
    try:
        if original_exists:
            stat_info = os.stat(original_path)
            original_size = stat_info.st_size
            original_mtime = stat_info.st_mtime
    except:
        pass
    
    rename_in_place = CONFIG.get("RENAME_IN_PLACE", "false").lower() in ("true", "1", "yes")
    original_dir = os.path.dirname(original_path)
    
    # Procura por arquivos processados
    search_dirs = []
    if rename_in_place:
        # Em modo RENAME_IN_PLACE, procura na mesma pasta
        search_dirs.append(original_dir)
    else:
        # Em modo normal, procura em OUTPUT_DIR
        search_dirs.append(CONFIG.get("OUTPUT_DIR", "/opt/nfse-renamer/files/processed"))
    
    current_time = time.time()
    
    for search_dir in search_dirs:
        if not os.path.exists(search_dir):
            continue
        
        try:
            # Procura por arquivos que começam com "nfse_" (minúsculo)
            for file in os.listdir(search_dir):
                if file.lower().startswith("nfse_") and file.lower().endswith(".pdf"):
                    processed_path = os.path.join(search_dir, file)
                    try:
                        stat_info = os.stat(processed_path)
                        file_mtime = stat_info.st_mtime
                        file_size = stat_info.st_size
                        
                        # Se o arquivo original não existe mais, qualquer arquivo "nfse_" 
                        # processado nos últimos 30 segundos pode ser o arquivo processado
                        if not original_exists:
                            if current_time - file_mtime < 30:
                                # Arquivo processado recentemente e original não existe = provavelmente foi processado
                                return processed_path
                        else:
                            # Se o arquivo original ainda existe, compara tamanho e data
                            if original_size and original_mtime:
                                size_diff = abs(file_size - original_size)
                                time_diff = abs(file_mtime - original_mtime)
                                
                                # Tamanho deve ser muito similar (diferença < 1KB)
                                # Data deve ser recente (últimos 10 segundos)
                                if size_diff < 1024 and time_diff < 10:
                                    # Arquivo encontrado - provavelmente foi processado
                                    return processed_path
                    except:
                        continue
        except Exception:
            continue
    
    return None

def process_pdf(path, retry_count=0):
    """
    Processa PDF com retry logic e tratamento robusto de erros
    """
    file_id = os.path.basename(path)
    
    # Evita processar o mesmo arquivo simultaneamente
    if file_id in PROCESSING_FILES:
        logging.warning(f"Arquivo já em processamento, ignorando: {path}")
        return False
    
    PROCESSING_FILES.add(file_id)
    
    try:
        # Validação inicial
        if not os.path.exists(path):
            logging.warning(f"Arquivo não encontrado: {path}")
            return False
        
        if not path.lower().endswith(".pdf"):
            logging.debug(f"Ignorando arquivo não-PDF: {path}")
            return False
        
        # IMPORTANTE: Não processa arquivos que estão em REJECT_DIR ou OUTPUT_DIR
        # Isso evita processar arquivos que já foram rejeitados ou processados
        if CONFIG["REJECT_DIR"] in path or path.startswith(CONFIG["REJECT_DIR"]):
            logging.debug(f"Ignorando arquivo em REJECT_DIR: {path}")
            return False
        
        if CONFIG["OUTPUT_DIR"] in path or path.startswith(CONFIG["OUTPUT_DIR"]):
            logging.debug(f"Ignorando arquivo em OUTPUT_DIR: {path}")
            return False
        
        # Verifica se o arquivo está em INPUT_DIR (pasta de entrada)
        # Só processa arquivos que estão na pasta de entrada
        if not path.startswith(CONFIG["INPUT_DIR"]):
            logging.debug(f"Ignorando arquivo fora de INPUT_DIR: {path}")
            return False
        
        # Verifica se arquivo deve ser processado (apenas os que começam com "NFSE" em maiúsculo)
        filename = os.path.basename(path)
        if not should_process_file(filename):
            logging.debug(f"Ignorando arquivo (não começa com NFSE_): {path}")
            return False
        
        # Aguarda arquivo estar pronto
        if not wait_for_file_ready(path):
            logging.warning(f"Arquivo não ficou disponível a tempo: {path}")
            if retry_count < int(CONFIG["MAX_RETRIES"]):
                sleep(int(CONFIG["RETRY_DELAY"]))
                PROCESSING_FILES.discard(file_id)
                return process_pdf(path, retry_count + 1)
            return False
        
        logging.info(f"Processando arquivo: {path}")
        
        # Processamento com timeout simulado
        start_time = time.time()
        try:
            new_name = extract_nfse_info(path)
        except Exception as extract_error:
            # Log específico para erros durante extração
            logging.error(f"Erro durante extração de informações: {path}")
            logging.error(f"  Tipo: {type(extract_error).__name__}")
            logging.error(f"  Mensagem: {str(extract_error)}")
            # Relança a exceção para ser tratada no bloco except externo
            raise
        elapsed = time.time() - start_time
        
        if elapsed > int(CONFIG["PROCESS_TIMEOUT"]):
            logging.warning(f"Processamento demorou {elapsed:.2f}s (timeout: {CONFIG['PROCESS_TIMEOUT']}s)")
        
        # Verifica se arquivo ainda existe antes de processar
        if not os.path.exists(path):
            logging.error(f"Arquivo foi removido durante processamento: {path}")
            return False
        
        # Verifica se deve renomear no lugar ou mover
        rename_in_place = CONFIG.get("RENAME_IN_PLACE", "false").lower() in ("true", "1", "yes")
        use_ftp = CONFIG.get("USE_FTP", "false").lower() in ("true", "1", "yes")
        
        if rename_in_place:
            # Renomeia na própria pasta INPUT_DIR
            dir_path = os.path.dirname(path)
            destino = os.path.join(dir_path, new_name + ".pdf")
            
            # Verifica se destino já existe
            if os.path.exists(destino):
                logging.warning(f"Arquivo destino já existe, adicionando timestamp: {destino}")
                base_name = new_name + "_" + str(int(time.time()))
                destino = os.path.join(dir_path, base_name + ".pdf")
            
            # Renomeia arquivo
            os.rename(path, destino)
            
            # Ajusta permissões do arquivo renomeado
            set_file_permissions(destino)
            
            logging.info(f"Arquivo renomeado com sucesso → {destino}")
            
            # Se FTP estiver habilitado, também faz upload
            if use_ftp:
                remote_filename = os.path.basename(destino)
                if upload_to_ftp(destino, remote_filename):
                    logging.info(f"Arquivo também enviado para FTP: {remote_filename}")
                else:
                    logging.warning(f"Falha ao enviar para FTP, mas arquivo local foi processado: {destino}")
        
        elif use_ftp:
            # Modo FTP: faz upload e remove arquivo local após sucesso
            remote_filename = new_name + ".pdf"
            
            if upload_to_ftp(path, remote_filename):
                # Remove arquivo local após upload bem-sucedido
                try:
                    os.remove(path)
                    logging.info(f"Arquivo enviado para FTP e removido localmente: {remote_filename}")
                except Exception as e:
                    logging.warning(f"Arquivo enviado para FTP, mas erro ao remover local: {e}")
            else:
                # Se falhar, move para OUTPUT_DIR como fallback
                logging.warning(f"Falha no upload FTP, movendo para OUTPUT_DIR como fallback")
                destino = os.path.join(CONFIG["OUTPUT_DIR"], new_name + ".pdf")
                if os.path.exists(destino):
                    base_name = new_name + "_" + str(int(time.time()))
                    destino = os.path.join(CONFIG["OUTPUT_DIR"], base_name + ".pdf")
                shutil.move(path, destino)
                set_file_permissions(destino)
                logging.info(f"Arquivo movido para OUTPUT_DIR: {destino}")
        
        else:
            # Comportamento padrão: move para OUTPUT_DIR
            destino = os.path.join(CONFIG["OUTPUT_DIR"], new_name + ".pdf")
            
            # Verifica se destino já existe
            if os.path.exists(destino):
                logging.warning(f"Arquivo destino já existe, adicionando timestamp: {destino}")
                base_name = new_name + "_" + str(int(time.time()))
                destino = os.path.join(CONFIG["OUTPUT_DIR"], base_name + ".pdf")
            
            # Move arquivo
            shutil.move(path, destino)
            
            # Ajusta permissões do arquivo processado
            set_file_permissions(destino)
            
            logging.info(f"Arquivo processado com sucesso → {destino}")
        
        return True
        
    except FileNotFoundError as e:
        logging.error(f"Arquivo não encontrado durante processamento: {path} - {e}")
        return False
    except PermissionError as e:
        logging.error(f"Erro de permissão ao processar {path}: {e}")
        if retry_count < int(CONFIG["MAX_RETRIES"]):
            sleep(int(CONFIG["RETRY_DELAY"]))
            PROCESSING_FILES.discard(file_id)
            return process_pdf(path, retry_count + 1)
        return False
    except (Exception, BaseException) as e:
        # Log de erro com mais detalhes para diferentes tipos de erro
        error_type = type(e).__name__
        error_msg = str(e)
        
        # Log mais detalhado para erros de leitura de PDF
        if "PdfminerException" in error_type or "PdfminerException" in error_msg or "No /Root" in error_msg:
            logging.error(f"Erro do pdfminer ao ler PDF: {path}")
            logging.error(f"  Detalhes: {error_msg}")
            logging.error(f"  Verificando se arquivo foi processado antes do erro...")
        elif "ValueError" in error_type and ("PDF não pode ser lido" in error_msg or "estrutura não padrão" in error_msg or "No /Root" in error_msg):
            logging.error(f"Erro ao ler PDF (estrutura não padrão): {path}")
            logging.error(f"  Detalhes: {error_msg}")
            logging.error(f"  Verificando se arquivo foi processado antes do erro...")
        elif "ValueError" in error_type and ("não encontrado" in error_msg or "não contém texto" in error_msg):
            logging.error(f"Erro ao extrair informações do PDF: {path}")
            logging.error(f"  Detalhes: {error_msg}")
            logging.error(f"  Verificando se arquivo foi processado antes do erro...")
        else:
            logging.error(f"Erro processando {path}: {error_type}: {error_msg}")
            logging.error(f"  Verificando se arquivo foi processado antes do erro...")
        
        # PRIMEIRO: Verifica se o arquivo foi processado antes de mover para REJECT_DIR
        # Isso é importante porque mesmo com erro, o arquivo pode ter sido renomeado/movido com sucesso
        processed_file = check_if_file_was_processed(path)
        if processed_file and os.path.exists(processed_file):
            logging.info(f"Arquivo foi processado com sucesso antes do erro: {path} → {processed_file}")
            logging.info(f"  Não movendo para REJECT_DIR pois o processamento foi bem-sucedido")
            return True  # Considera como sucesso pois foi processado
        
        # Se o arquivo original não existe mais e não encontramos processado, pode ter sido processado
        if not os.path.exists(path):
            logging.warning(f"Arquivo não encontrado após erro - pode ter sido processado: {path}")
            # Tenta uma busca mais ampla por arquivos processados recentes
            rename_in_place = CONFIG.get("RENAME_IN_PLACE", "false").lower() in ("true", "1", "yes")
            search_dir = os.path.dirname(path) if rename_in_place else CONFIG.get("OUTPUT_DIR", "/opt/nfse-renamer/files/processed")
            if os.path.exists(search_dir):
                try:
                    # Procura por qualquer arquivo "nfse_" processado nos últimos 10 segundos
                    current_time = time.time()
                    for file in os.listdir(search_dir):
                        if file.lower().startswith("nfse_") and file.lower().endswith(".pdf"):
                            file_path = os.path.join(search_dir, file)
                            try:
                                if current_time - os.path.getmtime(file_path) < 10:
                                    logging.info(f"Possível arquivo processado encontrado: {file_path}")
                                    return True  # Assume que foi processado
                            except:
                                pass
                except:
                    pass
            return False
        
        # Só move para REJECT_DIR se o arquivo ainda existir, não foi processado e está em INPUT_DIR
        # Verifica novamente se o arquivo ainda existe e está na pasta correta antes de mover
        if not os.path.exists(path):
            logging.warning(f"Arquivo não existe mais, não será movido para REJECT: {path}")
            return False
        
        # Verifica se o arquivo ainda está em INPUT_DIR (não foi movido por outro processo)
        if not path.startswith(CONFIG["INPUT_DIR"]):
            logging.warning(f"Arquivo não está mais em INPUT_DIR, não será movido para REJECT: {path}")
            return False
        
        try:
            reject_path = os.path.join(CONFIG["REJECT_DIR"], os.path.basename(path))
            # Evita sobrescrever arquivo existente em reject
            if os.path.exists(reject_path):
                base_name = os.path.splitext(os.path.basename(path))[0]
                reject_path = os.path.join(
                    CONFIG["REJECT_DIR"], 
                    f"{base_name}_{int(time.time())}.pdf"
                )
            
            # Move o arquivo para REJECT_DIR
            shutil.move(path, reject_path)
            
            # Ajusta permissões do arquivo rejeitado
            set_file_permissions(reject_path)
            
            logging.error(f"Arquivo movido para REJECT: {reject_path}")
            logging.error(f"Arquivo rejeitado não será processado novamente")
        except FileNotFoundError:
            # Arquivo foi removido/movido por outro processo
            logging.warning(f"Arquivo não encontrado ao tentar mover para REJECT (já foi movido?): {path}")
        except Exception as move_error:
            logging.error(f"Erro ao mover para REJECT: {move_error}")
        
        return False
    finally:
        PROCESSING_FILES.discard(file_id)

class NFSeHandler(FileSystemEventHandler):
    """Handler para eventos do watchdog"""
    def on_created(self, event):
        if event.is_directory:
            return
        if not event.src_path.lower().endswith(".pdf"):
            return
        
        # IMPORTANTE: Só processa arquivos que estão em INPUT_DIR
        # Ignora arquivos criados em outras pastas (REJECT_DIR, OUTPUT_DIR, etc)
        if not event.src_path.startswith(CONFIG["INPUT_DIR"]):
            logging.debug(f"Arquivo detectado fora de INPUT_DIR, ignorando: {event.src_path}")
            return
        
        # Processa apenas arquivos que começam com "NFSE" em maiúsculo
        filename = os.path.basename(event.src_path)
        if not should_process_file(filename):
            logging.debug(f"Arquivo detectado mas ignorado (não começa com NFSE_): {filename}")
            return
        
        logging.info(f"Arquivo detectado pelo watchdog: {filename}")
        # Processa em thread separada para não bloquear
        process_pdf(event.src_path)

def scan_directory():
    """Escaneia diretório em modo polling"""
    logging.info(f"Verificando pasta: {CONFIG['INPUT_DIR']}")
    pdf_files = []
    total_files = 0
    try:
        for file in os.listdir(CONFIG["INPUT_DIR"]):
            file_path = os.path.join(CONFIG["INPUT_DIR"], file)
            if os.path.isfile(file_path):
                total_files += 1
                if should_process_file(file):
                    pdf_files.append(file_path)
    except Exception as e:
        logging.error(f"Erro ao escanear diretório: {e}")
        return
    
    # Log do resultado da verificação
    if pdf_files:
        logging.info(f"Verificação concluída: {len(pdf_files)} arquivo(s) para processar (total: {total_files} arquivo(s) na pasta)")
    else:
        logging.info(f"Verificação concluída: nenhum arquivo para processar (total: {total_files} arquivo(s) na pasta)")
    
    for pdf_path in pdf_files:
        process_pdf(pdf_path)
    
    # Ajusta permissões de todos os PDFs nas pastas a cada ciclo
    fix_all_permissions()

def signal_handler(signum, frame):
    """Handler para sinais de sistema (SIGTERM, SIGINT)"""
    logging.info(f"Recebido sinal {signum}, encerrando serviço...")
    flush_logs()  # Garante que logs finais sejam escritos
    sys.exit(0)

def main():
    """Função principal do serviço"""
    # Configura handlers de sinal
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Carrega configuração
    try:
        load_config()
    except Exception as e:
        print(f"ERRO: Falha ao carregar configuração: {e}")
        sys.exit(1)
    
    # Configura logging
    setup_logging()
    
    logging.info("=" * 60)
    logging.info("NFSe Renamer Service iniciado")
    logging.info(f"INPUT_DIR: {CONFIG['INPUT_DIR']}")
    logging.info(f"OUTPUT_DIR: {CONFIG['OUTPUT_DIR']}")
    logging.info(f"REJECT_DIR: {CONFIG['REJECT_DIR']}")
    logging.info(f"POLLING_INTERVAL: {CONFIG['POLLING_INTERVAL']}s")
    logging.info(f"USE_POLLING: {CONFIG['USE_POLLING']}")
    logging.info(f"MAX_RETRIES: {CONFIG['MAX_RETRIES']}")
    logging.info(f"FILE_PERMISSIONS: {CONFIG['FILE_PERMISSIONS']} (octal)")
    logging.info(f"DIR_PERMISSIONS: {CONFIG['DIR_PERMISSIONS']} (octal)")
    logging.info(f"FIX_PERMISSIONS_ON_CYCLE: {CONFIG['FIX_PERMISSIONS_ON_CYCLE']}")
    logging.info(f"RENAME_IN_PLACE: {CONFIG['RENAME_IN_PLACE']}")
    logging.info("=" * 60)
    
    # Ajusta permissões dos diretórios na inicialização (apenas se existirem)
    logging.info("Ajustando permissões dos diretórios...")
    rename_in_place = CONFIG.get("RENAME_IN_PLACE", "false").lower() in ("true", "1", "yes")
    
    if os.path.exists(CONFIG["INPUT_DIR"]):
        set_directory_permissions(CONFIG["INPUT_DIR"])
    
    # REJECT_DIR sempre é usado (arquivos com erro são movidos para reject)
    if os.path.exists(CONFIG["REJECT_DIR"]):
        set_directory_permissions(CONFIG["REJECT_DIR"])
    
    # OUTPUT_DIR só é usado se não estiver em modo RENAME_IN_PLACE
    if not rename_in_place:
        if os.path.exists(CONFIG["OUTPUT_DIR"]):
            set_directory_permissions(CONFIG["OUTPUT_DIR"])
    
    use_polling = CONFIG["USE_POLLING"].lower() in ("true", "1", "yes")
    polling_interval = int(CONFIG["POLLING_INTERVAL"])
    
    if use_polling:
        # Modo polling
        logging.info("Modo POLLING ativado")
        try:
            while True:
                scan_directory()
                flush_logs()  # Garante que logs sejam escritos no arquivo
                sleep(polling_interval)
        except KeyboardInterrupt:
            logging.info("Serviço interrompido pelo usuário")
            flush_logs()
        except Exception as e:
            logging.error(f"Erro fatal no serviço: {type(e).__name__}: {str(e)}")
            flush_logs()
            sys.exit(1)
    else:
        # Modo watchdog (event-driven)
        logging.info("Modo WATCHDOG ativado")
        observer = Observer()
        event_handler = NFSeHandler()
        observer.schedule(event_handler, CONFIG["INPUT_DIR"], recursive=False)
        observer.start()
        
        try:
            last_permission_fix = time.time()
            last_verification = time.time()
            last_log_flush = time.time()
            permission_fix_interval = 300  # 5 minutos
            verification_interval = 60  # 1 minuto - verifica pasta periodicamente
            log_flush_interval = 10  # 10 segundos - força flush dos logs
            
            while True:
                sleep(1)
                current_time = time.time()
                
                # Força flush periódico dos logs para garantir escrita no arquivo
                if current_time - last_log_flush >= log_flush_interval:
                    flush_logs()
                    last_log_flush = current_time
                
                # Verifica pasta periodicamente no modo watchdog (para logs)
                if current_time - last_verification >= verification_interval:
                    try:
                        total_files = 0
                        pdf_files = []
                        for file in os.listdir(CONFIG["INPUT_DIR"]):
                            file_path = os.path.join(CONFIG["INPUT_DIR"], file)
                            if os.path.isfile(file_path):
                                total_files += 1
                                if should_process_file(file):
                                    pdf_files.append(file_path)
                        
                        if pdf_files:
                            logging.info(f"Verificação periódica: {len(pdf_files)} arquivo(s) para processar (total: {total_files} arquivo(s) na pasta {CONFIG['INPUT_DIR']})")
                        else:
                            logging.info(f"Verificação periódica: nenhum arquivo para processar (total: {total_files} arquivo(s) na pasta {CONFIG['INPUT_DIR']})")
                    except Exception as e:
                        logging.warning(f"Erro ao verificar pasta periodicamente: {e}")
                    
                    last_verification = current_time
                
                # Ajusta permissões periodicamente no modo watchdog
                if current_time - last_permission_fix >= permission_fix_interval:
                    fix_all_permissions()
                    last_permission_fix = current_time
        except KeyboardInterrupt:
            logging.info("Serviço interrompido pelo usuário")
            flush_logs()
            observer.stop()
        except Exception as e:
            logging.error(f"Erro fatal no serviço: {type(e).__name__}: {str(e)}")
            flush_logs()
            observer.stop()
            sys.exit(1)
        finally:
            observer.join()
            logging.info("Serviço NFSe Renamer encerrado")
            flush_logs()  # Garante que logs finais sejam escritos

if __name__ == "__main__":
    main()

