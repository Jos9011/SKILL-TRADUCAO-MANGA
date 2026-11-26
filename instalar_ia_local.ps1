# instalar_ia_local.ps1 - Instala a IA local (Ollama) para o Manga Studio e escolhe o modelo pela placa de vídeo.
# Rode pelo Instalar_IA_Local.bat (duplo clique). -Simular: só detecta e mostra o plano (usado no GitHub Actions).
# Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
param([switch]$Simular, [string]$Modelo = "")

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$OllamaDir = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
$OllamaExe = Join-Path $OllamaDir "ollama.exe"
$OllamaApp = Join-Path $OllamaDir "ollama app.exe"
$Api = "http://127.0.0.1:11434"

function Titulo($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }
function Ok($t) { Write-Host "[OK] $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "[!] $t" -ForegroundColor Yellow }

# ---------- 1. Placa de vídeo, memória e processador ----------
function Get-Gpus {
    $lista = @()
    $classe = "HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    $regs = @(Get-ChildItem $classe -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName -match '^\d{4}$' })
    foreach ($r in $regs) {
        $p = Get-ItemProperty $r.PSPath -ErrorAction SilentlyContinue
        if (-not $p -or -not $p.DriverDesc) { continue }
        $bytes = 0
        if ($p."HardwareInformation.qwMemorySize") { $bytes = [double]$p."HardwareInformation.qwMemorySize" }
        elseif ($p."HardwareInformation.MemorySize") { $bytes = [double]$p."HardwareInformation.MemorySize" }
        $nome = [string]$p.DriverDesc
        $dedicada = ($nome -match 'RX|RTX|GTX|Arc|Quadro|Radeon Pro|Titan') -or ($bytes -ge 3GB)
        $lista += [pscustomobject]@{ Nome = $nome; VramGB = [math]::Round($bytes / 1GB, 1); Dedicada = $dedicada }
    }
    if (-not $lista) {
        foreach ($v in Get-CimInstance Win32_VideoController) {
            $lista += [pscustomobject]@{ Nome = $v.Name; VramGB = [math]::Round([double]$v.AdapterRAM / 1GB, 1); Dedicada = ($v.Name -match 'RX|RTX|GTX|Arc') }
        }
    }
    return $lista
}

function Escolher-Plano($gpu, $ramGB) {
    $vram = 0; $fab = "nenhuma"
    if ($gpu) { $vram = $gpu.VramGB; if ($gpu.Nome -match 'NVIDIA|GeForce|RTX|GTX') { $fab = "nvidia" } elseif ($gpu.Nome -match 'AMD|Radeon') { $fab = "amd" } else { $fab = "outra" } }
    if ($vram -ge 14) { return @{ Modelo = "qwen3:14b"; Ctx = 16384; Prioridade = "first"; Reserva = "qwen3:8b"; Fab = $fab; Vram = $vram } }
    if ($vram -ge 10) { return @{ Modelo = "qwen3:8b"; Ctx = 16384; Prioridade = "first"; Reserva = "qwen3:4b"; Fab = $fab; Vram = $vram } }
    if ($vram -ge 6 -and $ramGB -ge 12) { return @{ Modelo = "qwen3:8b"; Ctx = 8192; Prioridade = "fallback"; Reserva = "qwen3:4b"; Fab = $fab; Vram = $vram } }
    return @{ Modelo = "qwen3:4b"; Ctx = 8192; Prioridade = "fallback"; Reserva = ""; Fab = $fab; Vram = $vram }
}

# ---------- 2. Vulkan: qual número é a placa dedicada (AMD sem ROCm, ex.: RX 5000) ----------
function Get-IndiceVulkanDedicada {
    $vi = Join-Path $env:WINDIR "System32\vulkaninfo.exe"
    if (-not (Test-Path $vi)) { return $null }
    try { $txt = & $vi --summary 2>$null | Out-String } catch { return $null }
    $idx = $null
    foreach ($linha in ($txt -split "`n")) {
        if ($linha -match '^\s*GPU(\d+):') { $atual = [int]$Matches[1] }
        if ($linha -match 'deviceType\s*=\s*PHYSICAL_DEVICE_TYPE_DISCRETE_GPU' -and $null -ne $atual) { $idx = $atual; break }
    }
    return $idx
}

# ---------- 3. Ollama: instalar, reiniciar com as variáveis, baixar e medir ----------
function Instalar-Ollama {
    if (Test-Path $OllamaExe) { Ok "Ollama já instalado."; return }
    Titulo "Instalando o Ollama"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements --silent
    }
    if (-not (Test-Path $OllamaExe)) {
        $setup = Join-Path $env:TEMP "OllamaSetup.exe"
        Write-Host "Baixando o instalador oficial (ollama.com)..."
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup -UseBasicParsing
        Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/NORESTART" -Wait
    }
    if (-not (Test-Path $OllamaExe)) { throw "O Ollama não foi instalado. Instale manualmente em https://ollama.com/download e rode este instalador de novo." }
    Ok "Ollama instalado."
}

function Reiniciar-Ollama {
    Get-Process -Name "ollama app", "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    if (Test-Path $OllamaApp) { Start-Process -FilePath $OllamaApp -WindowStyle Hidden }
    else { Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden }
    for ($i = 0; $i -lt 40; $i++) {
        try { Invoke-RestMethod "$Api/api/tags" -TimeoutSec 2 | Out-Null; return } catch { Start-Sleep -Seconds 1 }
    }
    throw "O servidor do Ollama não respondeu em $Api."
}

function Medir-Velocidade($modelo, $ctx) {
    $corpo = @{ model = $modelo; stream = $false; think = $false; keep_alive = "30m"
        messages = @(@{ role = "user"; content = 'Traduza para português do Brasil, só a tradução: "I told you not to come here alone!"' })
        options = @{ temperature = 0.2; num_predict = 48; num_ctx = $ctx } } | ConvertTo-Json -Depth 6
    Invoke-RestMethod "$Api/api/chat" -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($corpo)) -ContentType "application/json" -TimeoutSec 600 | Out-Null
    $r = Invoke-RestMethod "$Api/api/chat" -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($corpo)) -ContentType "application/json" -TimeoutSec 600
    $tok = 0
    if ($r.eval_duration -gt 0) { $tok = [math]::Round($r.eval_count / ($r.eval_duration / 1e9), 1) }
    return @{ TokS = $tok; Texto = ([string]$r.message.content).Trim() }
}

# ---------- 4. Manga Studio: gravar a configuração (sem BOM, para o Python ler) ----------
function Atualizar-Config($caminho, $plano) {
    $cfg = [ordered]@{}
    if (Test-Path $caminho) {
        $lido = Get-Content $caminho -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($p in $lido.PSObject.Properties) { $cfg[$p.Name] = $p.Value }
    }
    $cfg["ollama_host"] = "http://localhost:11434"
    $cfg["ollama_model"] = $plano.Modelo
    $cfg["ollama_num_ctx"] = $plano.Ctx
    $cfg["ollama_priority"] = $plano.Prioridade
    $cfg["ollama_timeout"] = 300
    if (-not $cfg.Contains("provider")) { $cfg["provider"] = "auto" }
    $pasta = Split-Path $caminho
    if (-not (Test-Path $pasta)) { New-Item -ItemType Directory -Path $pasta | Out-Null }
    $json = $cfg | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText($caminho, $json, (New-Object Text.UTF8Encoding $false))
    Ok "Configuração gravada em $caminho"
}

function Configs-Do-MangaStudio {
    # Versão pelo código: config.json da pasta do projeto. Versão .exe: %APPDATA%\MangaStudio\config.json.
    # Não cria o arquivo do .exe à toa: na 1ª execução ele copia as chaves da instalação antiga só se o arquivo não existir.
    $alvos = @()
    foreach ($pasta in @($PSScriptRoot, (Split-Path $PSScriptRoot))) {
        if ($pasta -and (Test-Path (Join-Path $pasta "auto_translate.py"))) { $alvos += (Join-Path $pasta "config.json") }
    }
    $doExe = Join-Path $env:APPDATA "MangaStudio\config.json"
    if ((Test-Path $doExe) -or (Test-Path (Join-Path $PSScriptRoot "MangaStudio.exe")) -or $alvos.Count -eq 0) { $alvos += $doExe }
    return $alvos | Select-Object -Unique
}

# ================= Execução =================
Titulo "Manga Studio: IA local no seu PC"
$gpus = @(Get-Gpus)
foreach ($g in $gpus) { Write-Host (" - Placa: {0} ({1} GB){2}" -f $g.Nome, $g.VramGB, $(if ($g.Dedicada) { " [dedicada]" } else { "" })) }
$gpu = $gpus | Where-Object { $_.Dedicada } | Sort-Object VramGB -Descending | Select-Object -First 1
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
Write-Host " - Processador: $cpu | RAM: $ramGB GB"

$plano = Escolher-Plano $gpu $ramGB
if ($Modelo) { $plano.Modelo = $Modelo; $plano.Reserva = "" }
$vkIdx = $null
if ($plano.Fab -eq "amd") { $vkIdx = Get-IndiceVulkanDedicada }

Titulo "Plano"
Write-Host " Modelo: $($plano.Modelo) (contexto de $($plano.Ctx) tokens)"
if ($plano.Prioridade -eq "fallback") { Write-Host " Uso: quando a nuvem (Groq/Gemini) ficar sem cota, no lugar de esperar." }
else { Write-Host " Uso: primeiro, sempre que estiver ligada (sem cota)." }
if ($plano.Fab -eq "amd") { Write-Host " Placa AMD: aceleração pelo Vulkan (já vem no driver). Placa no Vulkan: $(if ($null -ne $vkIdx) { "GPU$vkIdx" } else { 'automático' })" }
if ($plano.Fab -eq "nenhuma") { Aviso "Nenhuma placa de vídeo dedicada: a IA vai rodar no processador (mais devagar)." }
if ($Simular) { Ok "Simulação: nada foi instalado."; exit 0 }

Instalar-Ollama
Titulo "Ajustando o Ollama"
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH", [string]$plano.Ctx, "User")
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "30m", "User")
if ($plano.Fab -eq "amd") {
    [Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
    if ($null -ne $vkIdx) { [Environment]::SetEnvironmentVariable("GGML_VK_VISIBLE_DEVICES", [string]$vkIdx, "User") }
}
foreach ($n in "OLLAMA_CONTEXT_LENGTH", "OLLAMA_KEEP_ALIVE", "OLLAMA_VULKAN", "GGML_VK_VISIBLE_DEVICES") {
    $v = [Environment]::GetEnvironmentVariable($n, "User"); if ($v) { Set-Item -Path "Env:$n" -Value $v }
}
Reiniciar-Ollama
Ok "Servidor do Ollama ligado em $Api"

Titulo "Baixando $($plano.Modelo) (alguns GB, pode demorar)"
& $OllamaExe pull $plano.Modelo
if ($LASTEXITCODE -ne 0) { throw "Não foi possível baixar $($plano.Modelo)." }

Titulo "Testando a velocidade"
Aviso "Feche jogos e programas pesados: eles ocupam a memória da placa de vídeo."
$t = Medir-Velocidade $plano.Modelo $plano.Ctx
Write-Host " Tradução de teste: $($t.Texto)"
Write-Host " Velocidade: $($t.TokS) tokens/s"
if ($t.TokS -lt 6 -and $plano.Reserva) {
    Aviso "Lento demais para traduzir capítulos. Trocando para $($plano.Reserva), que é mais rápido."
    & $OllamaExe pull $plano.Reserva
    $plano.Modelo = $plano.Reserva
    $t = Medir-Velocidade $plano.Modelo $plano.Ctx
    Write-Host " Velocidade com $($plano.Modelo): $($t.TokS) tokens/s"
}

Titulo "Ligando ao Manga Studio"
foreach ($c in Configs-Do-MangaStudio) { Atualizar-Config $c $plano }

Titulo "Pronto"
Ok "IA local instalada: $($plano.Modelo) a $($t.TokS) tokens/s."
Write-Host " No Manga Studio, deixe o motor em 'Automático'. Em Configurações > IA local, 'Testar conexão e velocidade' confere tudo."
Write-Host " O Ollama abre sozinho com o Windows (ícone perto do relógio)."
