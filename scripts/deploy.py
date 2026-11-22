import os
import sys
import logging
from solcx import compile_standard, install_solc

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.connection import BlockchainConnection
from utils.config import NETWORKS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("DeployEngine")

install_solc("0.8.20")

ENV_PREFIXES = {
    "sepolia_testnet": "SEPOLIA",
    "arbitrum_sepolia": "ARB",
    "base_sepolia": "BASE",
    "polygon_amoy": "AMOY",
}


def compile_contract(file_path: str, contract_name: str):
    logger.info(f"A compilar o contrato {contract_name}...")
    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()

    compiled_sol = compile_standard(
        {
            "language": "Solidity",
            "sources": {file_path: {"content": source_code}},
            "settings": {
                "outputSelection": {
                    "*": {"*": ["abi", "evm.bytecode"]}
                }
            },
        },
        solc_version="0.8.20",
    )

    bytecode = compiled_sol["contracts"][file_path][contract_name]["evm"]["bytecode"]["object"]
    abi = compiled_sol["contracts"][file_path][contract_name]["abi"]
    return abi, bytecode


def deploy_contract(network_name: str, abi, bytecode, *constructor_args):
    conn = BlockchainConnection(network_name)
    w3 = conn.get_web3()
    account = w3.eth.account.from_key(conn.private_key)

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    # Margem de 2x no gasPrice para evitar rejeição por oscilação de baseFee
    safe_gas_price = int(w3.eth.gas_price * 2)

    logger.info(f"A enviar transação de deploy para a rede: {network_name}...")
    tx = contract.constructor(*constructor_args).build_transaction({
        "chainId": NETWORKS[network_name]["chain_id"],
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gasPrice": safe_gas_price,
    })

    signed_tx = w3.eth.account.sign_transaction(tx, conn.private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    logger.info(f"Transação enviada! Hash: {tx_hash.hex()}")

    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    logger.info(f"[✓] Contrato implantado com sucesso em: {tx_receipt.contractAddress}")
    return tx_receipt.contractAddress


def run_bridge_only_deploy(target_network: str, existing_token_address: str):
    logger.info(f"=== IMPLANTANDO APENAS O BRIDGESWAP NA REDE {target_network} ===")

    bridge_abi, bridge_bytecode = compile_contract("contracts/BridgeSwap.sol", "BridgeSwap")
    bridge_address = deploy_contract(target_network, bridge_abi, bridge_bytecode)

    prefix = ENV_PREFIXES.get(target_network, target_network.upper())

    print("\n" + "=" * 60)
    print("COPIE E COLE ESTAS LINHAS NO SEU FICHEIRO .env:")
    print(f"{prefix}_TOKEN_CONTRACT={existing_token_address}")
    print(f"{prefix}_BRIDGE_CONTRACT={bridge_address}")
    print("=" * 60 + "\n")


def run_full_deploy(target_network: str):
    logger.info(f"=== IMPLANTANDO TESTTOKEN + BRIDGESWAP NA REDE {target_network} ===")

    token_abi, token_bytecode = compile_contract("contracts/Token.sol", "TestToken")
    token_address = deploy_contract(target_network, token_abi, token_bytecode, "Bridge Test Token", "bTEST", 1000000)

    bridge_abi, bridge_bytecode = compile_contract("contracts/BridgeSwap.sol", "BridgeSwap")
    bridge_address = deploy_contract(target_network, bridge_abi, bridge_bytecode)

    prefix = ENV_PREFIXES.get(target_network, target_network.upper())

    print("\n" + "=" * 60)
    print("COPIE E COLE ESTAS LINHAS NO SEU FICHEIRO .env:")
    print(f"{prefix}_TOKEN_CONTRACT={token_address}")
    print(f"{prefix}_BRIDGE_CONTRACT={bridge_address}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    # Deploy completo na Polygon Amoy:
    run_full_deploy("polygon_amoy")

    # Alternativas para outras redes (se precisar):
    # run_full_deploy("base_sepolia")
    # run_bridge_only_deploy("arbitrum_sepolia", "0xfcd881EfE43631E31d54b3E04712CaC91AFBC899")