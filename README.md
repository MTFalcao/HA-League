# Ashen Heralds – HA-League  
Plataforma web para gestão e estatísticas de partidas de inhouse de :contentReference[oaicite:1]{index=1} entre amigos, com integração à API oficial da :contentReference[oaicite:2]{index=2}.

##  Objetivo  
- Permitir registro de jogadores e partidas de inhouse.  
- Exibir perfil, histórico de partidas, estatísticas de desempenho, campeões mais usados, win-rate e outras métricas úteis.  
- Facilitar bans/picks e planejamento do inhouse com base em dados reais.  
- Ser gratuito, simples e restrito ao grupo de amigos (não público).  

##  Tecnologias usadas  
- Backend: Python + Flask  
- Banco de dados: PostgreSQL  
- Cache de partidas: SQLite (via serviço de cache local)  
- Integração com API da Riot: endpoints oficiais Account, Summoner, League, Match-v5, Champion Mastery  
- Automação de inhouse/partidas: possível integração com bots via Discord.py  
- Frontend: HTML / CSS / JavaScript  
- Deploy/testes: Railway (ou servidor de sua escolha)  

## 🔧 Como configurar localmente (desenvolvimento)  

1. Clone o repositório:  
   ```bash
   git clone https://github.com/MTFalcao/HA-League.git
   cd HA-League
   ```

2. Crie e ative um ambiente virtual
   ```bash
   python -m venv venv
   ```
3. Instale dependências
   ```bash
   pip install -r requirements.txt
   ```
4. Crie um arquivo .env com as variáveis necessárias iguais a do [.env.example](.env.example)
5. Inicialize o banco PostgreSQL e preencha no .env igual no exemplo
6. Execute a aplicação
   ```bash
   python app.py
   ```

> Nota sobre API Key: Para testes locais, pode usar a dev-key da Riot, que é obtida em [Riot Games](https://developer.riotgames.com/). Para deploy em produção, use a personal key aprovada — observe eventual propagação da chave pelo servidor da Riot.
   
   
