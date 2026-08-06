@echo off
REM ============================================================================
REM  Coleta em laco, na maquina local.
REM
REM  Existe para os dias em que o GitHub Actions esta fora do ar. Faz o mesmo
REM  que o hunt-loop.yml: chama o hunt.py, espera 5 minutos, repete. Grava no
REM  mesmo Supabase, entao a pagina de clipping enxerga na hora.
REM
REM  Como saber se o Actions caiu: no run do workflow, o erro
REM  "The job was not acquired by Runner of type hosted" com duracao de
REM  ~15m 3s e falha de infraestrutura do GitHub, nao do robo. Nesse caso
REM  nao mexa em nada la; rode isto aqui ate o Actions voltar.
REM
REM  Para parar: Ctrl+C, e responda S quando perguntar.
REM ============================================================================

REM UTF-8 no console: o padrao do Windows e cp1252 e derruba o processo em
REM caractere acentuado. O hunt.py tambem se protege, mas isto evita que os
REM ecos deste .bat quebrem.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo ERRO: nao encontrei .venv\Scripts\python.exe
  echo Rode este arquivo de dentro de C:\health-ed-news-hunter
  echo.
  pause
  exit /b 1
)

set INTERVALO=300
set N=0

echo.
echo ==========================================================
echo  Health ^& Education News Hunter - coleta local
echo  Intervalo: %INTERVALO% segundos   ^|   Ctrl+C para parar
echo ==========================================================
echo.

:loop
set /a N=N+1
echo.
echo --------- iteracao %N% - %date% %time:~0,8% ---------
.venv\Scripts\python.exe hunt.py
if errorlevel 1 echo [aviso] a iteracao %N% terminou com erro - seguindo mesmo assim

REM O `timeout` mostra contagem regressiva, mas exige console interativo: se a
REM saida for redirecionada para arquivo ele morre com "nao ha suporte para o
REM redirecionamento de entrada" e o laco passa a rodar SEM espera nenhuma —
REM uma tempestade de requisicoes contra as fontes. O `ping` e o plano B: nao
REM depende de stdin e funciona em qualquer contexto. (+1 porque o primeiro
REM ping sai na hora.)
echo [aguardando %INTERVALO%s]
timeout /t %INTERVALO% /nobreak >nul 2>&1 || ping -n %INTERVALO% 127.0.0.1 >nul 2>&1
goto loop
