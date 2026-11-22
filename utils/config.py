import os
from dotenv import load_dotenv

load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY")

# Dicionário dinâmico com todas as redes EVM configuradas
NETWORKS = {
    "sepolia_testnet": {
        "rpc": os.getenv("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com"),
        "chain_id": 11155111,
        "token_contract": os.getenv("SEPOLIA_TOKEN_CONTRACT", "0x0000000000000000000000000000000000000000"),
        "bridge_contract": os.getenv("SEPOLIA_BRIDGE_CONTRACT", "0x0000000000000000000000000000000000000000"),
    },
    "arbitrum_sepolia": {
        "rpc": os.getenv("ARBITRUM_SEPOLIA_RPC_URL", "https://arbitrum-sepolia-rpc.publicnode.com"),
        "chain_id": 421614,
        "token_contract": os.getenv("ARB_TOKEN_CONTRACT", "0x0000000000000000000000000000000000000000"),
        "bridge_contract": os.getenv("ARB_BRIDGE_CONTRACT", "0x0000000000000000000000000000000000000000"),
    },
    "base_sepolia": {
        "rpc": os.getenv("BASE_SEPOLIA_RPC_URL", "https://base-sepolia-rpc.publicnode.com"),
        "chain_id": 84532,
        "token_contract": os.getenv("BASE_TOKEN_CONTRACT", "0x0000000000000000000000000000000000000000"),
        "bridge_contract": os.getenv("BASE_BRIDGE_CONTRACT", "0x0000000000000000000000000000000000000000"),
    },
    "polygon_amoy": {
        "rpc": os.getenv("POLYGON_AMOY_RPC_URL", "https://rpc-amoy.polygon.technology"),
        "chain_id": 80002,
        "token_contract": os.getenv("AMOY_TOKEN_CONTRACT", "0x0000000000000000000000000000000000000000"),
        "bridge_contract": os.getenv("AMOY_BRIDGE_CONTRACT", "0x0000000000000000000000000000000000000000"),
    }
}