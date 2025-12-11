#!/usr/bin/env python3
"""
NFSe Renamer Service - Serviço principal
"""
import os
import shutil
import logging
import signal
import sys
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
    
    # Criar diretórios se não existirem
    for dir_key in ["INPUT_DIR", "OUTPUT_DIR", "REJECT_DIR"]:
        os.makedirs(CONFIG[dir_key], exist_ok=True)
    
    # Criar diretório de logs
    log_dir = os.path.dirname(CONFIG["LOG_FILE"])
    os.makedirs(log_dir, exist_ok=True)

def setup_logging():
    """Configura sistema de logging"""
    logging.basicConfig(
        filename=CONFIG["LOG_FILE"],
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    # Também logar no console quando rodando como serviço
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(console_handler)

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
        
        # Verifica se arquivo ainda existe antes de mover
        if not os.path.exists(path):
            logging.error(f"Arquivo foi removido durante processamento: {path}")
            return False
        
        destino = os.path.join(CONFIG["OUTPUT_DIR"], new_name + ".pdf")
        
        # Verifica se destino já existe
        if os.path.exists(destino):
            logging.warning(f"Arquivo destino já existe, adicionando timestamp: {destino}")
            base_name = new_name + "_" + str(int(time.time()))
            destino = os.path.join(CONFIG["OUTPUT_DIR"], base_name + ".pdf")
        
        # Move arquivo
        shutil.move(path, destino)
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
        logging.error(f"Erro processando {path}: {type(e).__name__}: {e}", exc_info=True)
        
        # Move para reject apenas se arquivo ainda existir
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
                logging.error(f"Arquivo movido para REJECT: {reject_path}")
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
        # Processa em thread separada para não bloquear
        process_pdf(event.src_path)

def scan_directory():
    """Escaneia diretório em modo polling"""
    pdf_files = []
    try:
        for file in os.listdir(CONFIG["INPUT_DIR"]):
            file_path = os.path.join(CONFIG["INPUT_DIR"], file)
            if os.path.isfile(file_path) and file.lower().endswith(".pdf"):
                pdf_files.append(file_path)
    except Exception as e:
        logging.error(f"Erro ao escanear diretório: {e}")
    
    for pdf_path in pdf_files:
        process_pdf(pdf_path)

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
    logging.info("=" * 60)
    
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
            logging.error(f"Erro fatal no serviço: {e}", exc_info=True)
            sys.exit(1)
    else:
        # Modo watchdog (event-driven)
        logging.info("Modo WATCHDOG ativado")
        observer = Observer()
        event_handler = NFSeHandler()
        observer.schedule(event_handler, CONFIG["INPUT_DIR"], recursive=False)
        observer.start()
        
        try:
            while True:
                sleep(1)
        except KeyboardInterrupt:
            logging.info("Serviço interrompido pelo usuário")
            observer.stop()
        except Exception as e:
            logging.error(f"Erro fatal no serviço: {e}", exc_info=True)
            observer.stop()
            sys.exit(1)
        finally:
            observer.join()
            logging.info("Serviço NFSe Renamer encerrado")

if __name__ == "__main__":
    main()

