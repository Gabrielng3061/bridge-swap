# Portaldot — Multi-Chain Bridge & Swap Engine

Plataforma modular de **Bridge** e **Swap** cross-chain para redes EVM de teste (**Ethereum Sepolia**, **Arbitrum Sepolia**, **Base Sepolia** e **Polygon Amoy**), composta por contratos em Solidity (`^0.8.20`), *relayer* multi-thread em Python (`web3.py`) e interface web com `ethers.js`.

> **Aviso:** Projeto em ambiente de **testnet** para fins de desenvolvimento e validação técnica.

---

## Arquitetura

Usuário (Browser / Wallet)
       │
       ▼
frontend/index.html (Ethers.js v5)
       │  1. approve() + bridgeTokens() / swapTokens()
       ▼
contracts/BridgeSwap.sol (Origem)
       │  2. Emite evento TokensBridged
       ▼
scripts/run_bridge.py (Relayer Python multi-rede)
       │  3. Valida evento, confirmações, idempotência e cursor
       ▼
contracts/Token.sol (Destino) ──▶ Entrega de bTEST ao destinatário

### Estrutura do Repositório

portaldot-bridge-swap/
├── contracts/
│   ├── BridgeSwap.sol          # Contrato de bridge e swap com pausa, reentrância e separação de liquidez
│   ├── Token.sol               # Token ERC-20 de teste (bTEST)
│   ├── bridge_interface.py     # ABI da BridgeSwap
│   └── token_interface.py      # ABI do token ERC-20
├── core/
│   └── connection.py           # Conexão Web3 com retry e fallback de RPCs
├── frontend/
│   └── index.html              # Interface Web3 para Bridge e Swap
├── scripts/
│   ├── deploy.py               # Compilação (solcx) e deploy de contratos
│   ├── run_bridge.py           # Relayer multi-chain com persistência atômica e lock
│   ├── simulate_flow.py        # Simulação CLI de aprovação e bridge
│   ├── interact_contract.py    # Inspeção de estado e liquidez do contrato
│   └── test_connection.py      # Diagnóstico de RPC e saldo nativo nas redes
├── tests/
│   └── test_relayer_and_config.py
├── utils/
│   └── config.py               # Registro de redes, normalização de endereços e variáveis de ambiente
├── .env.example
└── requirements.txt

---

## Redes Suportadas

| Rede | Chave em `NETWORKS` | Chain ID |
| :--- | :--- | :--- |
| Ethereum Sepolia | `sepolia_testnet` | `11155111` |
| Arbitrum Sepolia | `arbitrum_sepolia` | `421614` |
| Base Sepolia | `base_sepolia` | `84532` |
| Polygon Amoy | `polygon_amoy` | `80002` |

---

## Configuração e Execução

1. Ambiente virtual e dependências:
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt pytest

2. Variáveis de ambiente:
   Copie .env.example para .env e preencha PRIVATE_KEY, RPCs e endereços de contrato por rede:
   Copy-Item .env.example .env

3. Testar conexões e suíte de testes:
   python scripts/test_connection.py
   python -m pytest -v

4. Rodar o Relayer multi-chain:
   python scripts/run_bridge.py

5. Abrir o Front-end:
   cd frontend
   python -m http.server 5050
   Acesse http://localhost:5050 no navegador.