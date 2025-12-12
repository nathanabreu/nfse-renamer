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
    """Configura sistema de logging"""
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
    
    # Configura formato
    log_format = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    
    # Handler para arquivo
    try:
        file_handler = logging.FileHandler(CONFIG["LOG_FILE"], mode='a', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(log_format)
        root_logger.addHandler(file_handler)
        
        # Testa se consegue escrever no arquivo
        logging.info("=" * 60)
        logging.info("Sistema de logging inicializado")
    except Exception as e:
        print(f"ERRO: Falha ao configurar arquivo de log {CONFIG['LOG_FILE']}: {e}")
        sys.exit(1)
    
    # Handler para console (apenas quando não rodando como serviço systemd)
    # O systemd já captura stdout/stderr, então não precisa duplicar
    if sys.stdout.isatty():  # Só adiciona se for terminal interativo
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(log_format)
        root_logger.addHandler(console_handler)
    
    root_logger.setLevel(logging.INFO)

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
        new_name = extract_nfse_info(path)
        elapsed = time.time() - start_time
        
        if elapsed > int(CONFIG["PROCESS_TIMEOUT"]):
            logging.warning(f"Processamento demorou {elapsed:.2f}s (timeout: {CONFIG['PROCESS_TIMEOUT']}s)")
        
        # Verifica se arquivo ainda existe antes de processar
        if not os.path.exists(path):
            logging.error(f"Arquivo foi removido durante processamento: {path}")
            return False
        
        # Verifica se deve renomear no lugar ou mover
        rename_in_place = CONFIG.get("RENAME_IN_PLACE", "false").lower() in ("true", "1", "yes")
        
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
    except Exception as e:
        # Log de erro com mais detalhes para diferentes tipos de erro
        error_type = type(e).__name__
        error_msg = str(e)
        
        # Log mais detalhado para erros de leitura de PDF
        if "ValueError" in error_type and ("PDF não pode ser lido" in error_msg or "estrutura não padrão" in error_msg or "No /Root" in error_msg):
            logging.error(f"Erro ao ler PDF (estrutura não padrão): {path}")
            logging.error(f"  Detalhes: {error_msg}")
            logging.error(f"  Sugestão: O PDF pode estar corrompido ou ter formato não suportado pelo pdfplumber")
        elif "ValueError" in error_type and ("não encontrado" in error_msg or "não contém texto" in error_msg):
            logging.error(f"Erro ao extrair informações do PDF: {path}")
            logging.error(f"  Detalhes: {error_msg}")
            logging.error(f"  Sugestão: O PDF pode não conter os campos esperados (CNPJ, RPS, NFSe, Série)")
        else:
            logging.error(f"Erro processando {path}: {error_type}: {error_msg}")
        
        # Sempre move arquivos com erro para REJECT_DIR (mesmo em modo RENAME_IN_PLACE)
        # Mas só se o arquivo ainda existir no caminho original
        try:
            if os.path.exists(path):
                reject_path = os.path.join(CONFIG["REJECT_DIR"], os.path.basename(path))
                # Evita sobrescrever arquivo existente em reject
                if os.path.exists(reject_path):
                    base_name = os.path.splitext(os.path.basename(path))[0]
                    reject_path = os.path.join(
                        CONFIG["REJECT_DIR"], 
                        f"{base_name}_{int(time.time())}.pdf"
                    )
                shutil.move(path, reject_path)
                
                # Ajusta permissões do arquivo rejeitado
                set_file_permissions(reject_path)
                
                logging.error(f"Arquivo movido para REJECT: {reject_path}")
            else:
                # Arquivo não existe mais - pode ter sido processado antes do erro
                logging.warning(f"Arquivo não encontrado após erro - pode ter sido processado antes da falha: {path}")
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
        # Processa apenas arquivos que começam com "NFSE" em maiúsculo
        filename = os.path.basename(event.src_path)
        if not should_process_file(filename):
            return
        # Processa em thread separada para não bloquear
        process_pdf(event.src_path)

def scan_directory():
    """Escaneia diretório em modo polling"""
    pdf_files = []
    try:
        for file in os.listdir(CONFIG["INPUT_DIR"]):
            file_path = os.path.join(CONFIG["INPUT_DIR"], file)
            if os.path.isfile(file_path) and should_process_file(file):
                pdf_files.append(file_path)
    except Exception as e:
        logging.error(f"Erro ao escanear diretório: {e}")
    
    for pdf_path in pdf_files:
        process_pdf(pdf_path)
    
    # Ajusta permissões de todos os PDFs nas pastas a cada ciclo
    fix_all_permissions()

def signal_handler(signum, frame):
    """Handler para sinais de sistema (SIGTERM, SIGINT)"""
    logging.info(f"Recebido sinal {signum}, encerrando serviço...")
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
                sleep(polling_interval)
        except KeyboardInterrupt:
            logging.info("Serviço interrompido pelo usuário")
        except Exception as e:
            logging.error(f"Erro fatal no serviço: {type(e).__name__}: {str(e)}")
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
            permission_fix_interval = 300  # 5 minutos
            
            while True:
                sleep(1)
                
                # Ajusta permissões periodicamente no modo watchdog
                current_time = time.time()
                if current_time - last_permission_fix >= permission_fix_interval:
                    fix_all_permissions()
                    last_permission_fix = current_time
        except KeyboardInterrupt:
            logging.info("Serviço interrompido pelo usuário")
            observer.stop()
        except Exception as e:
            logging.error(f"Erro fatal no serviço: {type(e).__name__}: {str(e)}")
            observer.stop()
            sys.exit(1)
        finally:
            observer.join()
            logging.info("Serviço NFSe Renamer encerrado")

if __name__ == "__main__":
    main()

