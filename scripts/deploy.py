import os
import sys
import json
import logging
from pathlib import Path
from solcx import compile_standard, install_solc

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.connection import BlockchainConnection
from utils.config import NETWORKS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("DeployEngine")

SOLC_VERSION = "0.8.20"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
OZ_CONTRACTS_DIR = PROJECT_ROOT / "node_modules" / "@openzeppelin" / "contracts"

ENV_PREFIXES = {
    "sepolia_testnet": "SEPOLIA",
    "arbitrum_sepolia": "ARB",
    "base_sepolia": "BASE",
    "polygon_amoy": "AMOY",
}


def ensure_solc():
    install_solc(SOLC_VERSION, show_progress=False)


def compile_contract(relative_file_path: str, contract_name: str, save_artifact: bool = True):
    """Compila usando Standard JSON com remappings do OpenZeppelin e salva artefato opcional."""
    ensure_solc()
    source_path = PROJECT_ROOT / relative_file_path
    if not source_path.exists():
        raise FileNotFoundError(f"Arquivo de contrato não encontrado: {source_path}")

    logger.info(f"Compilando {contract_name} a partir de {relative_file_path}...")
    source_code = source_path.read_text(encoding="utf-8")

    standard_input = {
        "language": "Solidity",
        "sources": {
            relative_file_path.replace("\\", "/"): {
                "content": source_code,
            }
        },
        "settings": {
            "optimizer": {
                "enabled": True,
                "runs": 200,
            },
            "remappings": [
                f"@openzeppelin/contracts/={OZ_CONTRACTS_DIR.as_posix()}/"
            ],
            "outputSelection": {
                "*": {
                    "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object"]
                }
            },
        },
    }

    compiled_sol = compile_standard(
        standard_input,
        solc_version=SOLC_VERSION,
        allow_paths=[OZ_CONTRACTS_DIR.as_posix(), PROJECT_ROOT.as_posix()],
    )

    source_key = relative_file_path.replace("\\", "/")
    contract_data = compiled_sol["contracts"][source_key][contract_name]
    abi = contract_data["abi"]
    bytecode = contract_data["evm"]["bytecode"]["object"]

    if not bytecode:
        raise RuntimeError(f"Bytecode vazio gerado para {contract_name}. Verifique imports e herança.")

    if save_artifact:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        artifact_file = ARTIFACTS_DIR / f"{contract_name}.json"
        artifact_payload = {
            "contractName": contract_name,
            "sourcePath": source_key,
            "compilerVersion": SOLC_VERSION,
            "abi": abi,
            "bytecode": bytecode,
        }
        artifact_file.write_text(json.dumps(artifact_payload, indent=2), encoding="utf-8")
        logger.info(f"Artefato salvo em: {artifact_file}")

    return abi, bytecode


def _send_built_tx(w3, tx: dict, private_key: str, error_msg: str):
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    raw_tx = getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction")
    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    logger.info(f"Transação enviada. Hash: {tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status != 1:
        raise RuntimeError(f"{error_msg} Hash: {tx_hash.hex()}")
    return receipt


def deploy_contract(network_name: str, abi, bytecode, *constructor_args):
    conn = BlockchainConnection(network_name)
    w3 = conn.get_web3()
    account = w3.eth.account.from_key(conn.private_key)

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    nonce = w3.eth.get_transaction_count(account.address, "pending")
    safe_gas_price = int(w3.eth.gas_price * 2)

    logger.info(f"Enviando deploy de contrato para '{network_name}' a partir de {account.address}...")
    tx = contract.constructor(*constructor_args).build_transaction({
        "chainId": NETWORKS[network_name]["chain_id"],
        "from": account.address,
        "nonce": nonce,
        "gas": 3_500_000,
        "gasPrice": safe_gas_price,
    })

    receipt = _send_built_tx(
        w3,
        tx,
        conn.private_key,
        f"Deploy falhou (status=0) na rede {network_name}.",
    )
    logger.info(f"[✓] Contrato implantado em: {receipt.contractAddress}")
    return receipt.contractAddress, w3, account, conn.private_key


def configure_target_chains(
    network_name: str,
    bridge_address: str,
    abi,
    account,
    private_key: str,
    w3,
    target_chain_ids: list[int],
):
    """Habilita as cadeias de destino permitidas no BridgeSwap pós-deploy."""
    if not target_chain_ids:
        return

    bridge = w3.eth.contract(address=w3.to_checksum_address(bridge_address), abi=abi)
    current_nonce = w3.eth.get_transaction_count(account.address, "pending")
    safe_gas_price = int(w3.eth.gas_price * 2)
    tx_index = 0

    for chain_id in target_chain_ids:
        if chain_id == NETWORKS[network_name]["chain_id"]:
            continue
        tx = bridge.functions.setTargetChainAllowed(chain_id, True).build_transaction({
            "chainId": NETWORKS[network_name]["chain_id"],
            "from": account.address,
            "nonce": current_nonce + tx_index,
            "gasPrice": safe_gas_price,
        })
        _send_built_tx(
            w3,
            tx,
            private_key,
            f"Falha ao habilitar targetChainId {chain_id} em {bridge_address}.",
        )
        logger.info(f"[✓] Cadeia de destino {chain_id} habilitada em {bridge_address}")
        tx_index += 1


def seed_swap_liquidity(
    network_name: str,
    bridge_address: str,
    bridge_abi,
    token_address: str,
    token_abi,
    amount_wei: int,
    account,
    private_key: str,
    w3,
):
    """Faz approve e depositSwapLiquidity para habilitar o token no pool de swap."""
    bridge_cs = w3.to_checksum_address(bridge_address)
    token_cs = w3.to_checksum_address(token_address)

    token = w3.eth.contract(address=token_cs, abi=token_abi)
    bridge = w3.eth.contract(address=bridge_cs, abi=bridge_abi)

    nonce = w3.eth.get_transaction_count(account.address, "pending")
    safe_gas_price = int(w3.eth.gas_price * 2)
    chain_id = NETWORKS[network_name]["chain_id"]

    approve_tx = token.functions.approve(bridge_cs, amount_wei).build_transaction({
        "chainId": chain_id,
        "from": account.address,
        "nonce": nonce,
        "gasPrice": safe_gas_price,
    })
    _send_built_tx(w3, approve_tx, private_key, f"Falha no approve de {token_cs} para {bridge_cs}.")
    logger.info(f"[✓] Approve concluído para {bridge_cs}")

    deposit_tx = bridge.functions.depositSwapLiquidity(token_cs, amount_wei).build_transaction({
        "chainId": chain_id,
        "from": account.address,
        "nonce": nonce + 1,
        "gasPrice": safe_gas_price,
    })
    _send_built_tx(w3, deposit_tx, private_key, f"Falha em depositSwapLiquidity de {token_cs}.")
    logger.info(f"[✓] Liquidez de swap depositada para {token_cs}")


def run_bridge_and_swap_token_deploy(
    target_network: str,
    max_operation_amount_wei: int = 1_000_000 * 10**18,
    allowed_target_chain_ids: list[int] | None = None,
    initial_swap_liquidity_wei: int = 10_000 * 10**18,
):
    """Implanta o novo BridgeSwap e o TestSwapToken (tUSDC), configura rotas e abastece liquidez."""
    logger.info(f"=== IMPLANTANDO BRIDGESWAP + TESTSWAPTOKEN NA REDE {target_network} ===")

    conn = BlockchainConnection(target_network)
    w3_init = conn.get_web3()
    deployer_addr = w3_init.eth.account.from_key(conn.private_key).address

    bridge_abi, bridge_bytecode = compile_contract("contracts/BridgeSwap.sol", "BridgeSwap")
    bridge_address, w3, account, private_key = deploy_contract(
        target_network,
        bridge_abi,
        bridge_bytecode,
        deployer_addr,
        max_operation_amount_wei,
    )

    swap_token_abi, swap_token_bytecode = compile_contract("contracts/TestSwapToken.sol", "TestSwapToken")
    swap_token_address, _, _, _ = deploy_contract(
        target_network,
        swap_token_abi,
        swap_token_bytecode,
        "Test Swap Token",
        "tUSDC",
        1_000_000 * 10**18,
    )

    if allowed_target_chain_ids:
        configure_target_chains(
            target_network, bridge_address, bridge_abi, account, private_key, w3, allowed_target_chain_ids
        )

    if initial_swap_liquidity_wei > 0:
        seed_swap_liquidity(
            target_network,
            bridge_address,
            bridge_abi,
            swap_token_address,
            swap_token_abi,
            initial_swap_liquidity_wei,
            account,
            private_key,
            w3,
        )

    prefix = ENV_PREFIXES.get(target_network, target_network.upper())
    print("\n" + "=" * 60)
    print("COPIE E COLE ESTAS LINHAS NO SEU FICHEIRO .env:")
    print(f"{prefix}_BRIDGE_CONTRACT={bridge_address}")
    print(f"{prefix}_SWAP_TOKEN_CONTRACT={swap_token_address}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    target_net = sys.argv[1] if len(sys.argv) > 1 else "sepolia_testnet"
    if target_net not in NETWORKS:
        print(f"Rede inválida: '{target_net}'. Redes disponíveis: {list(NETWORKS.keys())}")
        sys.exit(1)

    all_testnet_chain_ids = [
        cfg["chain_id"] for cfg in NETWORKS.values() if cfg.get("chain_id") is not None
    ]
    run_bridge_and_swap_token_deploy(
        target_net,
        max_operation_amount_wei=1_000_000 * 10**18,
        allowed_target_chain_ids=all_testnet_chain_ids,
        initial_swap_liquidity_wei=10_000 * 10**18,
    )