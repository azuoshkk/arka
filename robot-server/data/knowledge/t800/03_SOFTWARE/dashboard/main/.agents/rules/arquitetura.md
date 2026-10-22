# REGRAS E DIRETRIZES DE ARQUITETURA PARA AGENTES DE IA (DASHGROUP ARCANJO)

Ao trabalhar neste projeto de dashboard para o robô T800, siga rigorosamente as diretrizes consolidadas no documento oficial:
👉 [ESTRUTURA_E_GUIA_IA.md](file:///Users/beniprado/Library/CloudStorage/GoogleDrive-beniprado015@gmail.com/Outros%20computadores/Home-PC/Progamações/MyRobot/dashboard/ESTRUTURA_E_GUIA_IA.md)

## Regras Fundamentais:
1. **Nunca poluir a raiz**: Não coloque scripts, wrappers ou arquivos soltos na raiz. O backend roda em `ros2_websocket_bridge.py` + módulos em `modules_dashboard/`.
2. **Arquitetura Modular no Backend**: Novos nós e serviços ROS 2 devem herdar de `BaseModule` (`modules_dashboard/common/base_module.py`) e ser registrados no `ProcessManager`.
3. **Novas Abas e Telas**: Devem ser registradas formalmente em `src/config/tabs.ts` (`DASHBOARD_TABS`) e renderizadas na casca principal `src/app/page.tsx`.
4. **Sem Componentes Órfãos**: Todo componente criado em `src/components/` deve ter uso claro e imediato em uma view ou tela ativa.
5. **Tipagem Estrita**: Adicione novas estruturas de dados em `src/lib/telemetry/types.ts`.
6. **Não inchar o useWebSocket.ts**: Separe lógicas complexas em sub-hooks ou contextos modulares.
7. **Critério de Conclusão**: Teste com `python3 -m unittest discover tests` e `npx tsc --noEmit`. Atualize `version.ts` e `README.md` conforme `INSTRUCOES.md`.
8. **Preservar Nomes Canônicos**: Nunca altere títulos, nomes de componentes, banners de console ou logs canônicos por causa de novas adições ou otimizações (ex: manter sempre `DASHGROUP ARCANJO — ORQUESTRADOR CENTRAL T800`, sem sufixos como `(ZERO-DELAY)`, `(NOVA VERSÃO)`, etc.).

