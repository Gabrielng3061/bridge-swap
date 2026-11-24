import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
PRIVATE_KEY = (os.getenv("PRIVATE_KEY") or "").strip()


def _normalize_address(raw_addr: str | None) -> str:
    cleaned = (raw_addr or "").strip()
    if not cleaned or cleaned == "0x...":
        return ZERO_ADDRESS
    if Web3.is_address(cleaned):
        return Web3.to_checksum_address(cleaned)
    return ZERO_ADDRESS


def _parse_fallback_rpcs(env_var_name: str) -> list[str]:
    raw = (os.getenv(env_var_name) or "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


NETWORKS = {
    "sepolia_testnet": {
        "rpc": os.getenv("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com"),
        "fallback_rpcs": _parse_fallback_rpcs("SEPOLIA_FALLBACK_RPCS"),
        "chain_id": 11155111,
        "token_contract": _normalize_address(os.getenv("SEPOLIA_TOKEN_CONTRACT")),
        "bridge_contract": _normalize_address(os.getenv("SEPOLIA_BRIDGE_CONTRACT")),
    },
    "arbitrum_sepolia": {
        "rpc": os.getenv("ARBITRUM_SEPOLIA_RPC_URL", "https://arbitrum-sepolia-rpc.publicnode.com"),
        "fallback_rpcs": _parse_fallback_rpcs("ARB_FALLBACK_RPCS"),
        "chain_id": 421614,
        "token_contract": _normalize_address(os.getenv("ARB_TOKEN_CONTRACT")),
        "bridge_contract": _normalize_address(os.getenv("ARB_BRIDGE_CONTRACT")),
    },
    "base_sepolia": {
        "rpc": os.getenv("BASE_SEPOLIA_RPC_URL", "https://base-sepolia-rpc.publicnode.com"),
        "fallback_rpcs": _parse_fallback_rpcs("BASE_FALLBACK_RPCS"),
        "chain_id": 84532,
        "token_contract": _normalize_address(os.getenv("BASE_TOKEN_CONTRACT")),
        "bridge_contract": _normalize_address(os.getenv("BASE_BRIDGE_CONTRACT")),
    },
    "polygon_amoy": {
        "rpc": os.getenv("POLYGON_AMOY_RPC_URL", "https://polygon-amoy-bor-rpc.publicnode.com"),
        "fallback_rpcs": _parse_fallback_rpcs("AMOY_FALLBACK_RPCS"),
        "chain_id": 80002,
        "token_contract": _normalize_address(os.getenv("AMOY_TOKEN_CONTRACT")),
        "bridge_contract": _normalize_address(os.getenv("AMOY_BRIDGE_CONTRACT")),
    },
}


def get_configured_networks() -> list[str]:
    """Retorna redes com token_contract e bridge_contract válidos."""
    active = []
    for net_name, cfg in NETWORKS.items():
        if cfg["token_contract"] != ZERO_ADDRESS and cfg["bridge_contract"] != ZERO_ADDRESS:
            active.append(net_name)
    return active