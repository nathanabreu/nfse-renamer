#!/bin/bash
#
# Script de instalação do NFSe Renamer Service
# Este script instala e configura o serviço no Linux
#

set -e  # Para em caso de erro

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Verificar se está rodando como root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}ERRO: Este script precisa ser executado como root${NC}"
    echo "Use: sudo $0"
    exit 1
fi

# Diretório base
INSTALL_DIR="/opt/nfse-renamer"
CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Detectar configuração de proxy
PIP_PROXY=""
if [ -n "$http_proxy" ] || [ -n "$HTTP_PROXY" ]; then
    PIP_PROXY="${http_proxy:-$HTTP_PROXY}"
elif [ -n "$https_proxy" ] || [ -n "$HTTPS_PROXY" ]; then
    PIP_PROXY="${https_proxy:-$HTTPS_PROXY}"
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}NFSe Renamer Service - Instalação${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Informar sobre proxy se detectado
if [ -n "$PIP_PROXY" ]; then
    echo -e "${YELLOW}ℹ Proxy detectado: $PIP_PROXY${NC}"
    echo ""
fi

# 1. Verificar se o diretório de instalação existe
if [ ! -d "$CURRENT_DIR" ]; then
    echo -e "${RED}ERRO: Diretório do serviço não encontrado: $CURRENT_DIR${NC}"
    exit 1
fi

# 2. Criar diretórios necessários
echo -e "${YELLOW}[1/6] Criando diretórios...${NC}"
mkdir -p "$INSTALL_DIR/files/inbound"
mkdir -p "$INSTALL_DIR/files/processed"
mkdir -p "$INSTALL_DIR/files/reject"
mkdir -p "$INSTALL_DIR/logs"
echo -e "${GREEN}✓ Diretórios criados${NC}"

# 3. Copiar arquivos para diretório de instalação
echo -e "${YELLOW}[2/6] Copiando arquivos...${NC}"
if [ "$CURRENT_DIR" != "$INSTALL_DIR" ]; then
    cp -r "$CURRENT_DIR"/* "$INSTALL_DIR/" 2>/dev/null || {
        # Se falhar, tentar copiar arquivo por arquivo
        cp -r "$CURRENT_DIR/src" "$INSTALL_DIR/"
        cp -r "$CURRENT_DIR/docs" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$CURRENT_DIR/config.env" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$CURRENT_DIR/nfse-renamer.service" "$INSTALL_DIR/" 2>/dev/null || true
    }
    echo -e "${GREEN}✓ Arquivos copiados para $INSTALL_DIR${NC}"
else
    echo -e "${GREEN}✓ Arquivos já estão em $INSTALL_DIR${NC}"
fi

# 4. Ajustar permissões
echo -e "${YELLOW}[3/6] Ajustando permissões...${NC}"
chown -R root:root "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR/src"
chmod +x "$INSTALL_DIR/src/__main__.py" 2>/dev/null || true
echo -e "${GREEN}✓ Permissões ajustadas${NC}"

# 5. Instalar dependências Python
echo -e "${YELLOW}[4/6] Instalando dependências Python...${NC}"
if command -v pip3 &> /dev/null; then
    # Preparar comando pip3 com proxy se necessário
    PIP_CMD="pip3 install"
    if [ -n "$PIP_PROXY" ]; then
        PIP_CMD="pip3 install --proxy $PIP_PROXY"
        echo -e "${YELLOW}  Usando proxy: $PIP_PROXY${NC}"
    fi
    
    # Tentar instalação normal primeiro
    if $PIP_CMD watchdog pdfplumber 2>/dev/null; then
        echo -e "${GREEN}✓ Dependências instaladas${NC}"
    else
        # Se falhar, tentar com --break-system-packages
        echo -e "${YELLOW}  Tentando com --break-system-packages...${NC}"
        if [ -n "$PIP_PROXY" ]; then
            PIP_CMD="pip3 install --break-system-packages --proxy $PIP_PROXY"
        else
            PIP_CMD="pip3 install --break-system-packages"
        fi
        
        if $PIP_CMD watchdog pdfplumber; then
            echo -e "${GREEN}✓ Dependências instaladas${NC}"
        else
            echo -e "${RED}ERRO: Falha ao instalar dependências${NC}"
            if [ -n "$PIP_PROXY" ]; then
                echo "  Tente manualmente: pip3 install --break-system-packages --proxy $PIP_PROXY watchdog pdfplumber"
            else
                echo "  Tente manualmente: pip3 install --break-system-packages watchdog pdfplumber"
            fi
            echo ""
            echo -e "${YELLOW}  Dica: Se estiver em ambiente com proxy, configure as variáveis:${NC}"
            echo "    export http_proxy='http://proxy.empresa.com:8080'"
            echo "    export https_proxy='http://proxy.empresa.com:8080'"
            echo "    sudo -E $0"
            exit 1
        fi
    fi
else
    echo -e "${RED}ERRO: pip3 não encontrado${NC}"
    echo "  Instale Python 3 e pip3 primeiro"
    exit 1
fi

# 6. Verificar se dependências estão instaladas
echo -e "${YELLOW}[5/6] Verificando dependências...${NC}"
if python3 -c "import watchdog; import pdfplumber" 2>/dev/null; then
    echo -e "${GREEN}✓ Dependências verificadas${NC}"
else
    echo -e "${RED}ERRO: Dependências não estão disponíveis${NC}"
    exit 1
fi

# 7. Configurar systemd
echo -e "${YELLOW}[6/6] Configurando systemd...${NC}"
if [ -f "$INSTALL_DIR/nfse-renamer.service" ]; then
    cp "$INSTALL_DIR/nfse-renamer.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable nfse-renamer
    echo -e "${GREEN}✓ Serviço configurado no systemd${NC}"
else
    echo -e "${RED}ERRO: Arquivo nfse-renamer.service não encontrado${NC}"
    exit 1
fi

# 8. Iniciar serviço
echo ""
echo -e "${YELLOW}Iniciando serviço...${NC}"
if systemctl start nfse-renamer; then
    sleep 2
    if systemctl is-active --quiet nfse-renamer; then
        echo -e "${GREEN}✓ Serviço iniciado com sucesso${NC}"
    else
        echo -e "${RED}ERRO: Serviço não está rodando${NC}"
        echo "  Verifique os logs: journalctl -u nfse-renamer -n 50"
        exit 1
    fi
else
    echo -e "${RED}ERRO: Falha ao iniciar serviço${NC}"
    echo "  Verifique os logs: journalctl -u nfse-renamer -n 50"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Instalação concluída com sucesso!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Comandos úteis:"
echo "  Status do serviço:  systemctl status nfse-renamer"
echo "  Ver logs:            journalctl -u nfse-renamer -f"
echo "  Reiniciar:           systemctl restart nfse-renamer"
echo "  Parar:               systemctl stop nfse-renamer"
echo ""
echo "Arquivo de log: $INSTALL_DIR/logs/nfse_renamer.log"
echo "Diretório de entrada: $INSTALL_DIR/files/inbound"
echo ""

