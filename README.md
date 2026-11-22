# EVM Modular Cross-Chain Bridge & Swap Engine

A professional, EVM-agnostic, multi-network **Bridge & Swap Engine** designed for high-performance token transfers and liquidity routing across EVM compatible networks (including Portaldot V3 Testnet, Ethereum Sepolia, Polygon, and local EVM nodes).

---

## 🏗️ Architecture Overview

The application adopts a **Modular Adapter Pattern** separating Smart Contracts, Relayer Execution Engines, Network Configurations, and User Interfaces:

```text
portaldot-bridge-swap/
├── contracts/             # Solidity v0.8.20 Contracts & Python ABIs
│   ├── BridgeSwap.sol     # Central Lock, Release & Swap Smart Contract
│   ├── Token.sol          # Mintable ERC-20 Test Token
│   ├── bridge_interface.py# Bridge Contract ABI Mapping
│   └── token_interface.py # ERC-20 Token ABI Mapping
├── core/                  # EVM Multi-Network Core Provider
│   └── connection.py      # Resilient Web3 Connector
├── scripts/               # Automation & Relayer Scripts
│   ├── deploy.py          # Automated Contract Compiler & Deployer
│   ├── run_bridge.py      # Event-driven Relayer Engine (Web3 Event Listener)
│   ├── simulate_flow.py   # End-to-End Execution Simulator
│   └── test_connection.py # Multi-Network RPC Health Checker
├── utils/                 # Application Configuration & Network Registry
│   └── config.py          # Centralized Network Environment Registry
├── frontend/              # Web3 Front-End Interface
│   └── index.html         # Minimalist Ethers.js DApp User Interface
└── .env                   # Environment Private Key and RPC URLs