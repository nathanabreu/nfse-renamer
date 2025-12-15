# Script para gerar pacote de deploy do NFSe Renamer Service
# Gera um arquivo ZIP com estrutura pronta para instalação no Linux

param(
    [string]$OutputDir = ".\deploy",
    [switch]$IncludeVersion = $true
)

# Cores para output
function Write-ColorOutput($ForegroundColor) {
    $fc = $host.UI.RawUI.ForegroundColor
    $host.UI.RawUI.ForegroundColor = $ForegroundColor
    if ($args) {
        Write-Output $args
    }
    $host.UI.RawUI.ForegroundColor = $fc
}

Write-ColorOutput Green "========================================"
Write-ColorOutput Green "NFSe Renamer Service - Gerador de Deploy"
Write-ColorOutput Green "========================================"
Write-Output ""

# Verificar se está no diretório correto
if (-not (Test-Path "src")) {
    Write-ColorOutput Red "ERRO: Diretório 'src' não encontrado"
    Write-Output "Execute este script a partir da raiz do projeto"
    exit 1
}

# Obter versão do projeto
$Version = "1.0.0"
if (Test-Path "src\__init__.py") {
    $InitContent = Get-Content "src\__init__.py" -Raw
    if ($InitContent -match '__version__\s*=\s*["'']([^"'']+)["'']') {
        $Version = $Matches[1]
    }
}

# Criar diretório de output se não existir
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

# Nome do arquivo ZIP
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if ($IncludeVersion) {
    $ZipName = "nfse-renamer-v$Version-$Timestamp.zip"
} else {
    $ZipName = "nfse-renamer-$Timestamp.zip"
}
$ZipPath = Join-Path $OutputDir $ZipName

Write-ColorOutput Yellow "Gerando pacote de deploy..."
Write-Output "  Versão: $Version"
Write-Output "  Arquivo: $ZipName"
Write-Output "  Estrutura: Pronta para instalação em /opt/nfse-renamer/"
Write-Output ""

# Criar diretório temporário com estrutura Linux
$TempDir = Join-Path $env:TEMP "nfse-renamer-deploy-$(Get-Random)"
$LinuxRoot = Join-Path $TempDir "nfse-renamer"
New-Item -ItemType Directory -Path $LinuxRoot -Force | Out-Null

try {
    Write-ColorOutput Yellow "[1/7] Copiando arquivos necessários..."
    
    # Copiar arquivos e diretórios
    $ItemsToCopy = @{
        "src" = "src"
        "docs" = "docs"
        "scripts" = "scripts"
        "config.env" = "config.env"
        "nfse-renamer.service" = "nfse-renamer.service"
    }
    
    foreach ($Source in $ItemsToCopy.Keys) {
        $Dest = $ItemsToCopy[$Source]
        if (Test-Path $Source) {
            $SourcePath = $Source
            $DestPath = Join-Path $LinuxRoot $Dest
            Copy-Item -Path $SourcePath -Destination $DestPath -Recurse -Force
            Write-Output "  ✓ $Source -> $Dest"
        } else {
            Write-ColorOutput Yellow "  ⚠ $Source não encontrado (pode ser opcional)"
        }
    }
    
    Write-ColorOutput Yellow "[2/7] Criando estrutura de diretórios..."
    
    # Criar diretórios vazios necessários (estrutura completa)
    $DirsToCreate = @(
        "files\inbound",
        "files\processed",
        "files\reject",
        "logs"
    )
    
    foreach ($Dir in $DirsToCreate) {
        $DirPath = Join-Path $LinuxRoot $Dir
        New-Item -ItemType Directory -Path $DirPath -Force | Out-Null
        Write-Output "  ✓ Criado: $Dir"
    }
    
    # Criar arquivo .gitkeep em logs para garantir que a pasta seja incluída no ZIP
    $LogsKeepFile = Join-Path $LinuxRoot "logs\.gitkeep"
    New-Item -ItemType File -Path $LogsKeepFile -Force | Out-Null
    
    Write-ColorOutput Yellow "[3/7] Removendo arquivos desnecessários..."
    
    # Remover arquivos Python compilados
    Get-ChildItem -Path $LinuxRoot -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue | Remove-Item -Force
    Get-ChildItem -Path $LinuxRoot -Recurse -Filter "__pycache__" -Directory -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
    
    # Remover arquivos de log existentes (mas manter a pasta logs/)
    Get-ChildItem -Path $LinuxRoot -Recurse -Filter "*.log" -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike "*\logs\*" } | Remove-Item -Force
    # Remover logs da pasta logs/ também (manter apenas estrutura)
    Get-ChildItem -Path (Join-Path $LinuxRoot "logs") -Filter "*.log" -ErrorAction SilentlyContinue | Remove-Item -Force
    
    # Remover arquivos temporários e de sistema
    Get-ChildItem -Path $LinuxRoot -Recurse -Filter "*.tmp" -ErrorAction SilentlyContinue | Remove-Item -Force
    Get-ChildItem -Path $LinuxRoot -Recurse -Filter ".DS_Store" -ErrorAction SilentlyContinue | Remove-Item -Force
    Get-ChildItem -Path $LinuxRoot -Recurse -Filter "Thumbs.db" -ErrorAction SilentlyContinue | Remove-Item -Force
    
    # Remover diretórios de desenvolvimento (mas manter files/ e logs/ que criamos)
    $DevDirs = @(".git", ".vscode", ".idea")
    foreach ($Dir in $DevDirs) {
        $DirPath = Join-Path $LinuxRoot $Dir
        if (Test-Path $DirPath) {
            Remove-Item -Path $DirPath -Recurse -Force -ErrorAction SilentlyContinue
            Write-Output "  ✓ Removido: $Dir"
        }
    }
    
    # Limpar conteúdo de files/ mas manter estrutura
    $FilesDirs = @("files\inbound", "files\processed", "files\reject")
    foreach ($Dir in $FilesDirs) {
        $DirPath = Join-Path $LinuxRoot $Dir
        if (Test-Path $DirPath) {
            Get-ChildItem -Path $DirPath -File -ErrorAction SilentlyContinue | Remove-Item -Force
            Write-Output "  ✓ Limpo: $Dir"
        }
    }
    
    Write-Output "  ✓ Arquivos temporários removidos"
    
    Write-ColorOutput Yellow "[4/7] Ajustando permissões de scripts..."
    
    # Garantir que scripts bash sejam executáveis (simulado no ZIP)
    # Nota: Permissões reais serão definidas no Linux durante instalação
    $Scripts = @(
        "scripts\install.sh",
        "scripts\run_local.sh"
    )
    
    foreach ($Script in $Scripts) {
        $ScriptPath = Join-Path $LinuxRoot $Script
        if (Test-Path $ScriptPath) {
            # Verificar se começa com shebang
            $Content = Get-Content $ScriptPath -Raw
            if (-not $Content.StartsWith("#!")) {
                Write-ColorOutput Yellow "  ⚠ $Script não tem shebang"
            }
        }
    }
    
    Write-Output "  ✓ Scripts verificados"
    
    Write-ColorOutput Yellow "[5/7] Verificando estrutura..."
    
    # Verificar arquivos essenciais
    $EssentialFiles = @(
        "src\__init__.py",
        "src\__main__.py",
        "src\nfse_service.py",
        "src\extract_nfse_info.py",
        "config.env",
        "nfse-renamer.service",
        "scripts\install.sh",
        "docs\README_NFSE_RENAMER.md"
    )
    
    $MissingFiles = @()
    foreach ($File in $EssentialFiles) {
        $FullPath = Join-Path $LinuxRoot $File
        if (-not (Test-Path $FullPath)) {
            $MissingFiles += $File
        }
    }
    
    if ($MissingFiles.Count -gt 0) {
        Write-ColorOutput Red "  ERRO: Arquivos essenciais não encontrados:"
        foreach ($File in $MissingFiles) {
            Write-ColorOutput Red "    - $File"
        }
        throw "Arquivos essenciais faltando"
    }
    
    # Verificar estrutura de diretórios
    $EssentialDirs = @(
        "files\inbound",
        "files\processed",
        "files\reject",
        "logs"
    )
    
    foreach ($Dir in $EssentialDirs) {
        $DirPath = Join-Path $LinuxRoot $Dir
        if (-not (Test-Path $DirPath)) {
            Write-ColorOutput Yellow "  ⚠ Diretório não encontrado: $Dir"
        }
    }
    
    Write-Output "  ✓ Estrutura verificada"
    
    Write-ColorOutput Yellow "[6/7] Criando arquivo ZIP..."
    
    # Remover ZIP anterior se existir
    if (Test-Path $ZipPath) {
        Remove-Item $ZipPath -Force
    }
    
    # Criar ZIP com estrutura nfse-renamer/ na raiz
    # Isso permite: unzip arquivo.zip -d /opt/ e ter /opt/nfse-renamer/ pronto
    Compress-Archive -Path "$LinuxRoot\*" -DestinationPath $ZipPath -Force
    
    Write-Output "  ✓ ZIP criado"
    
    Write-ColorOutput Yellow "[7/7] Verificando arquivo ZIP..."
    
    # Verificar se ZIP foi criado e tem tamanho razoável
    $ZipInfo = Get-Item $ZipPath
    if ($ZipInfo.Length -lt 1024) {
        Write-ColorOutput Red "  AVISO: Arquivo ZIP muito pequeno ($($ZipInfo.Length) bytes)"
    } else {
        Write-Output "  ✓ Arquivo ZIP válido ($([math]::Round($ZipInfo.Length / 1KB, 2)) KB)"
    }
    
    Write-Output ""
    Write-ColorOutput Green "========================================"
    Write-ColorOutput Green "Deploy gerado com sucesso!"
    Write-ColorOutput Green "========================================"
    Write-Output ""
    Write-Output "Arquivo: $ZipPath"
    Write-Output "Tamanho: $([math]::Round($ZipInfo.Length / 1KB, 2)) KB"
    Write-Output ""
    Write-Output "Estrutura do ZIP (pronta para instalação):"
    Write-Output "  nfse-renamer/"
    Write-Output "    ├── src/ (código-fonte Python)"
    Write-Output "    ├── docs/ (documentação)"
    Write-Output "    ├── scripts/ (scripts de instalação)"
    Write-Output "    ├── files/ (estrutura de diretórios)"
    Write-Output "    │   ├── inbound/"
    Write-Output "    │   ├── processed/"
    Write-Output "    │   └── reject/"
    Write-Output "    ├── logs/ (pasta para logs - vazia)"
    Write-Output "    ├── config.env (configuração)"
    Write-Output "    └── nfse-renamer.service (systemd service)"
    Write-Output ""
    Write-Output "Instalação no Linux:"
    Write-Output "  1. unzip $ZipName -d /opt/"
    Write-Output "  2. cd /opt/nfse-renamer"
    Write-Output "  3. sudo ./scripts/install.sh"
    Write-Output ""
    Write-ColorOutput Yellow "Pronto para envio ao cliente!"
    
} catch {
    Write-ColorOutput Red ""
    Write-ColorOutput Red "ERRO ao gerar deploy:"
    Write-ColorOutput Red $_.Exception.Message
    exit 1
} finally {
    # Limpar diretório temporário
    if (Test-Path $TempDir) {
        Remove-Item $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

