"""
Módulo de Contratos: Armazena a ABI genérica e o endereço oficial da BridgeSwap.
"""

BRIDGE_ABI = [
    # --- FUNÇÕES DE ESCRITA (Write) ---
    {
        "inputs": [
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "uint256", "name": "targetChainId", "type": "uint256"}
        ],
        "name": "bridgeTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "tokenIn", "type": "address"},
            {"internalType": "address", "name": "tokenOut", "type": "address"},
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "minAmountOut", "type": "uint256"}
        ],
        "name": "swapTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"}
        ],
        "name": "emergencyWithdraw",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },

    # --- FUNÇÕES DE LEITURA (View/Read) ---
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "lockedLiquidity",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },

    # --- EVENTOS (Escutados pelo Relayer Python) ---
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "sender", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "token", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "targetChainId", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "timestamp", "type": "uint256"}
        ],
        "name": "TokensBridged",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "tokenIn", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "tokenOut", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "amountOut", "type": "uint256"}
        ],
        "name": "TokensSwapped",
        "type": "event"
    }
]

# Endereço temporário de testes (atualizar após o deploy)
BRIDGE_CONTRACT_ADDRESS = "0x0000000000000000000000000000000000000000"