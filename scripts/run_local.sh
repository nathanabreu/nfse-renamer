#!/bin/bash
#
# Script para executar o NFSe Renamer Service localmente
# Útil para desenvolvimento e testes
#

set -e  # Para em caso de erro

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Diretório do projeto
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Detectar configuração de proxy
PIP_PROXY=""
if [ -n "$http_proxy" ] || [ -n "$HTTP_PROXY" ]; then
    PIP_PROXY="${http_proxy:-$HTTP_PROXY}"
elif [ -n "$https_proxy" ] || [ -n "$HTTPS_PROXY" ]; then
    PIP_PROXY="${https_proxy:-$HTTPS_PROXY}"
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}NFSe Renamer Service - Execução Local${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Informar sobre proxy se detectado
if [ -n "$PIP_PROXY" ]; then
    echo -e "${YELLOW}ℹ Proxy detectado: $PIP_PROXY${NC}"
    echo ""
fi

# Verificar se está no diretório correto
if [ ! -d "$PROJECT_DIR/src" ]; then
    echo -e "${RED}ERRO: Diretório src não encontrado${NC}"
    echo "  Execute este script a partir da raiz do projeto"
    exit 1
fi

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERRO: python3 não encontrado${NC}"
    exit 1
fi

# Verificar dependências
echo -e "${YELLOW}Verificando dependências...${NC}"
if ! python3 -c "import watchdog" 2>/dev/null; then
    echo -e "${YELLOW}  watchdog não encontrado, instalando...${NC}"
    if [ -n "$PIP_PROXY" ]; then
        PIP_CMD="pip3 install --proxy $PIP_PROXY"
        PIP_CMD_BREAK="pip3 install --break-system-packages --proxy $PIP_PROXY"
    else
        PIP_CMD="pip3 install"
        PIP_CMD_BREAK="pip3 install --break-system-packages"
    fi
    
    if $PIP_CMD watchdog 2>/dev/null || $PIP_CMD_BREAK watchdog 2>/dev/null; then
        echo -e "${GREEN}  ✓ watchdog instalado${NC}"
    else
        echo -e "${RED}ERRO: Falha ao instalar watchdog${NC}"
        exit 1
    fi
fi

if ! python3 -c "import pdfplumber" 2>/dev/null; then
    echo -e "${YELLOW}  pdfplumber não encontrado, instalando...${NC}"
    if [ -n "$PIP_PROXY" ]; then
        PIP_CMD="pip3 install --proxy $PIP_PROXY"
        PIP_CMD_BREAK="pip3 install --break-system-packages --proxy $PIP_PROXY"
    else
        PIP_CMD="pip3 install"
        PIP_CMD_BREAK="pip3 install --break-system-packages"
    fi
    
    if $PIP_CMD pdfplumber 2>/dev/null || $PIP_CMD_BREAK pdfplumber 2>/dev/null; then
        echo -e "${GREEN}  ✓ pdfplumber instalado${NC}"
    else
        echo -e "${RED}ERRO: Falha ao instalar pdfplumber${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓ Dependências verificadas${NC}"
echo ""

# Verificar se config.env existe
if [ ! -f "$PROJECT_DIR/config.env" ]; then
    echo -e "${YELLOW}Arquivo config.env não encontrado, criando padrão...${NC}"
    cat > "$PROJECT_DIR/config.env" << EOF
INPUT_DIR="$PROJECT_DIR/files/inbound"
OUTPUT_DIR="$PROJECT_DIR/files/processed"
REJECT_DIR="$PROJECT_DIR/files/reject"
LOG_FILE="$PROJECT_DIR/logs/nfse_renamer.log"

USE_POLLING="false"
POLLING_INTERVAL="5"
MAX_RETRIES="3"
RETRY_DELAY="2"
PROCESS_TIMEOUT="60"
FILE_PERMISSIONS="644"
DIR_PERMISSIONS="755"
FIX_PERMISSIONS_ON_CYCLE="true"
RENAME_IN_PLACE="false"
EOF
    echo -e "${GREEN}✓ config.env criado${NC}"
fi

# Criar diretórios se não existirem
echo -e "${YELLOW}Criando diretórios necessários...${NC}"
mkdir -p "$PROJECT_DIR/files/inbound"
mkdir -p "$PROJECT_DIR/files/processed"
mkdir -p "$PROJECT_DIR/files/reject"
mkdir -p "$PROJECT_DIR/logs"
echo -e "${GREEN}✓ Diretórios criados${NC}"
echo ""

# Mostrar informações
echo -e "${GREEN}Configuração:${NC}"
echo "  Diretório do projeto: $PROJECT_DIR"
echo "  Diretório de entrada: $PROJECT_DIR/files/inbound"
echo "  Arquivo de log: $PROJECT_DIR/logs/nfse_renamer.log"
echo ""
echo -e "${YELLOW}Iniciando serviço...${NC}"
echo -e "${YELLOW}(Pressione Ctrl+C para parar)${NC}"
echo ""
echo -e "${GREEN}========================================${NC}"
echo ""

# Mudar para o diretório do projeto
cd "$PROJECT_DIR"

# Executar o serviço
python3 -m src

