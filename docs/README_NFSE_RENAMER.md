# 📄 NFSe Renamer Service — README

Serviço Linux em Python para extração automática de metadados de NFSe (Prefeitura de Porto Alegre) a partir de arquivos PDF, com renomeação padronizada e movimentação por diretórios monitorados.

O objetivo é garantir que todos os PDFs entregues ao conector fiscal sigam o padrão definido pelo cliente:

nfse_<CNPJ_EMITENTE>_<NUM_RPS>_<NUM_NFSE>_<SERIE>.pdf


Exemplo real extraído do PDF:

nfse_02886427002450_146345_8_1.pdf

## ✔️ 1. Arquitetura da Solução

A solução é composta por quatro módulos principais:

1. **Monitoramento de Diretório** (Watchdog ou Polling)

   - **Modo Watchdog (padrão)**: Monitoramento contínuo via biblioteca watchdog/inotify. Dispara processamento imediatamente ao detectar criação de novos PDFs. Mais eficiente e responsivo.
   
   - **Modo Polling**: Verifica o diretório em intervalos configuráveis. Útil quando inotify não está disponível ou para ambientes com restrições específicas. Frequência configurável via `POLLING_INTERVAL`.

2. **Extractor NFSe**

   Módulo dedicado à extração estruturada dos campos:
   - CNPJ Emitente
   - RPS (Número)
   - Série
   - NFSe (Número da Nota)
   
   Usa regex, normalização e leitura via pdfplumber.

3. **Dispatcher com Retry Logic**

   Movimenta arquivos para:
   - `/processed` → sucesso
   - `/reject` → erro de leitura/extração após todas as tentativas
   
   Inclui sistema robusto de retry, validação de arquivos e tratamento de erros.

4. **systemd Service**

   Executa o serviço de forma contínua, resiliente e auditável, com:
   - Restart automático em caso de falha
   - Logs integrados ao journald
   - Controle de recursos e timeouts
   - Política de restart configurável

## ✔️ 2. Estrutura de Diretórios
```
/opt/nfse-renamer/
│
├── config.env               # Configurações parametrizadas
├── nfse-renamer.service     # Arquivo systemd
│
├── src/                     # ✅ Todo o código-fonte do serviço
│   ├── __init__.py          # Pacote Python
│   ├── __main__.py          # Ponto de entrada (execução como módulo)
│   ├── nfse_service.py      # Lógica principal do serviço
│   └── extract_nfse_info.py # Módulo de extração NFSe
│
├── docs/                    # Documentação
│   └── README_NFSE_RENAMER.md
│
├── files/                   # Diretórios de trabalho
│   ├── inbound/             # PDFs de entrada (monitorado)
│   ├── processed/           # PDFs processados com sucesso
│   └── reject/              # PDFs rejeitados
│
└── logs/                    # Arquivos de log
    └── nfse_renamer.log
```

## ✔️ 3. Instalação
1. Criar diretório base
```bash
mkdir -p /opt/nfse-renamer/files/{inbound,processed,reject}
mkdir -p /opt/nfse-renamer/logs
```

2. Descompactar o ZIP
unzip nfse-renamer.zip -d /opt/

3. Instalar bibliotecas Python
pip3 install watchdog pdfplumber

4. Configurar o systemd
```bash
cp /opt/nfse-renamer/nfse-renamer.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable nfse-renamer
systemctl start nfse-renamer
```

5. Verificar
```bash
systemctl status nfse-renamer
```

### Características do Serviço systemd

O arquivo `nfse-renamer.service` foi configurado com:

- ✅ **Restart automático**: Reinicia automaticamente em caso de falha
- ✅ **Política de restart inteligente**: Limita tentativas excessivas (5 tentativas em 5 minutos)
- ✅ **Logs integrados**: Logs disponíveis via `journalctl`
- ✅ **Timeout de parada**: 30 segundos para encerramento gracioso
- ✅ **Segurança**: `NoNewPrivileges` e `PrivateTmp` habilitados
- ✅ **Documentação**: Link para README no systemd

### Logs do Serviço

**Logs em tempo real**:
```bash
journalctl -u nfse-renamer -f
```

**Últimas 100 linhas**:
```bash
journalctl -u nfse-renamer -n 100
```

**Logs desde hoje**:
```bash
journalctl -u nfse-renamer --since today
```

## ✔️ 4. Funcionamento do Serviço

### Fluxo Operacional

1. **Usuário coloca um PDF** em `/opt/nfse-renamer/files/inbound/`

2. **Detecção automática**:
   - **Modo Watchdog**: Detecta imediatamente via inotify
   - **Modo Polling**: Detecta no próximo ciclo de verificação (configurável)

3. **Validação e preparação**:
   - Aguarda arquivo estar completamente escrito
   - Verifica se não está em uso por outro processo
   - Valida extensão PDF

4. **Extração de metadados** (com retry em caso de erro):
   - CNPJ emitente
   - RPS
   - Número da Nota (NFSe)
   - Série

5. **Geração do novo nome**:
   ```
   nfse_<cnpj>_<rps>_<nfse>_<serie>.pdf
   ```

6. **Movimentação**:
   - `/processed` → sucesso
   - `/reject` → falha após todas as tentativas (log detalhado gerado)

### Características de Robustez

- ✅ **Retry automático**: Até 3 tentativas em caso de erro temporário
- ✅ **Validação de arquivo**: Aguarda arquivo estar completamente escrito
- ✅ **Prevenção de duplicatas**: Evita processar o mesmo arquivo simultaneamente
- ✅ **Timeout de processamento**: Limite configurável para evitar travamentos
- ✅ **Tratamento de arquivos em uso**: Detecta e aguarda liberação
- ✅ **Logs detalhados**: Todos os eventos são registrados com stack trace em erros

## ✔️ 5. Configuração Parametrizada (config.env)

Arquivo central de configuração com todas as opções disponíveis:

### Diretórios

```bash
INPUT_DIR="/opt/nfse-renamer/files/inbound"
OUTPUT_DIR="/opt/nfse-renamer/files/processed"
REJECT_DIR="/opt/nfse-renamer/files/reject"
LOG_FILE="/opt/nfse-renamer/logs/nfse_renamer.log"
```

### Modo de Operação e Frequência

```bash
# Modo de operação: "true" para polling, "false" para watchdog (event-driven)
USE_POLLING="false"

# Intervalo de verificação em segundos (apenas quando USE_POLLING=true)
# Exemplo: 5 = verifica a cada 5 segundos, 30 = a cada 30 segundos
POLLING_INTERVAL="5"
```

**Recomendações**:
- Use `USE_POLLING="false"` (watchdog) para melhor desempenho e resposta imediata
- Use `USE_POLLING="true"` apenas se inotify não estiver disponível ou houver restrições específicas
- Para polling, ajuste `POLLING_INTERVAL` conforme necessidade:
  - **5-10 segundos**: Alta frequência, maior uso de recursos
  - **30-60 segundos**: Frequência moderada, balanceado
  - **300+ segundos**: Baixa frequência, menor uso de recursos

### Resistência a Erros

```bash
# Número máximo de tentativas em caso de erro
MAX_RETRIES="3"

# Tempo de espera entre tentativas (segundos)
RETRY_DELAY="2"

# Timeout máximo para processamento de um arquivo (segundos)
PROCESS_TIMEOUT="60"
```

**Explicação**:
- `MAX_RETRIES`: Quantas vezes o serviço tentará processar um arquivo antes de mover para `/reject`
- `RETRY_DELAY`: Tempo de espera entre cada tentativa (útil para arquivos ainda sendo escritos)
- `PROCESS_TIMEOUT`: Limite máximo de tempo para processar um arquivo (evita travamentos)

Altere conforme necessidade de cada cliente/ambiente.

## ✔️ 6. Regras de Extração (Regex)
Campo	Regex
CNPJ do Emitente	\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b
Número da Nota (NFSe)	Número da Nota\s*([0-9]{1,10})
RPS Número	RPS Nº\s*([0-9]+)
Série	Série\s*([0-9]+)

Essas regex foram testadas com PDFs reais da Prefeitura de Porto Alegre.

## ✔️ 7. Tratamento de Erros

### Sistema de Retry Automático

O serviço implementa um sistema robusto de retry que tenta processar arquivos até `MAX_RETRIES` vezes antes de movê-los para `/reject`. Isso garante que erros temporários (arquivo ainda sendo escrito, rede instável, etc.) não resultem em rejeição imediata.

### Situações que levam à pasta /reject (após todas as tentativas):

- PDF sem texto legível
- Campos obrigatórios ausentes
- PDF corrompido
- Permissão negada ao mover (após retries)
- Timeout de processamento excedido
- Erro de leitura persistente

### Validações Implementadas

- ✅ **Aguarda arquivo estar pronto**: Verifica se arquivo foi completamente escrito antes de processar
- ✅ **Detecção de arquivo em uso**: Evita processar arquivos que estão sendo acessados por outros processos
- ✅ **Prevenção de duplicatas**: Evita processar o mesmo arquivo simultaneamente
- ✅ **Validação de destino**: Verifica se arquivo destino já existe e adiciona timestamp se necessário
- ✅ **Tratamento de exceções**: Captura e registra todos os tipos de erro com stack trace completo

### Logs

Todos os eventos são logados em:
- **Arquivo de log**: `/opt/nfse-renamer/logs/nfse_renamer.log`
- **Journald**: `journalctl -u nfse-renamer -f` (logs do systemd)

Os logs incluem:
- Informações de processamento bem-sucedido
- Avisos sobre arquivos em uso ou timeouts
- Erros detalhados com stack trace
- Movimentações para `/reject` com motivo

## ✔️ 8. Atualização do Serviço

### Atualizar Configuração

Editar `config.env`:
```bash
vim /opt/nfse-renamer/config.env
```

Recarregar serviço (não requer restart, mas recomendado):
```bash
systemctl restart nfse-renamer
```

### Atualizar Código

Todos os arquivos de código estão em `/opt/nfse-renamer/src/`:
```bash
vim /opt/nfse-renamer/src/nfse_service.py
vim /opt/nfse-renamer/src/extract_nfse_info.py
```

Recarregar serviço:
```bash
systemctl restart nfse-renamer
```

**Nota**: O serviço é executado como módulo Python (`python3 -m src`), garantindo que todo o código fique organizado na pasta `src/`.

### Verificar Status

```bash
# Status do serviço
systemctl status nfse-renamer

# Logs em tempo real
journalctl -u nfse-renamer -f

# Últimas 50 linhas de log
journalctl -u nfse-renamer -n 50
```

## ✔️ 9. Testes
1. Copie um PDF válido para inbound:
cp exemplo.pdf /opt/nfse-renamer/inbound/

2. Observe processamento:
journalctl -u nfse-renamer -f

3. Verifique saída:
/opt/nfse-renamer/processed/nfse_<cnpj>_<rps>_<nfse>_<serie>.pdf

## ✔️ 10. Troubleshooting

### ❗ Serviço não inicia

**Verificar permissões**:
```bash
chown -R root:root /opt/nfse-renamer
chmod -R 755 /opt/nfse-renamer/src
```

**Verificar dependências**:
```bash
pip3 install watchdog pdfplumber
```

**Verificar configuração**:
```bash
# Verificar se config.env existe e está correto
cat /opt/nfse-renamer/config.env

# Verificar se diretórios existem
ls -la /opt/nfse-renamer/
```

**Verificar logs do systemd**:
```bash
journalctl -u nfse-renamer -n 100
```

### ❗ PDF não aparece na pasta processed

**Consultar logs**:
```bash
# Log do arquivo
tail -n 50 /opt/nfse-renamer/logs/nfse_renamer.log

# Log do systemd
journalctl -u nfse-renamer -n 50
```

**Verificar se arquivo está em /reject**:
```bash
ls -la /opt/nfse-renamer/reject/
```

**Verificar se arquivo ainda está em /inbound**:
```bash
ls -la /opt/nfse-renamer/inbound/
```

### ❗ Regex não encontrou campos

- Verificar se PDF é da Prefeitura de Porto Alegre
- Enviar exemplo de PDF para revisão da regex
- Verificar se PDF contém texto legível (não é apenas imagem)

### ❗ Serviço reinicia constantemente

**Verificar logs para identificar erro**:
```bash
journalctl -u nfse-renamer -n 100 --no-pager
```

**Verificar configuração do systemd**:
```bash
systemctl cat nfse-renamer
```

**Ajustar política de restart** (se necessário):
Editar `/etc/systemd/system/nfse-renamer.service` e ajustar `StartLimitInterval` e `StartLimitBurst`.

### ❗ Arquivos ficam presos em /inbound

- Verificar permissões de escrita em `/processed` e `/reject`
- Verificar espaço em disco: `df -h`
- Consultar logs para erros específicos
- Verificar se arquivo está sendo usado por outro processo: `lsof /opt/nfse-renamer/inbound/arquivo.pdf`

## ✔️ 11. Roadmap Futuro

Processamento paralelo

API REST para consulta de status

Registro de auditoria Syslog

Regras customizadas por município

## ✔️ 12. Autor / Suporte Técnico

NFSe Renamer Service
Desenvolvido para automação de integração fiscal, padrão corporativo e alto desempenho operacional.

Para evoluções, troubleshooting e extensões, abra issue no repositório.