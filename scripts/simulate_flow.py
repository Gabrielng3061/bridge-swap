import os
import sys
import time
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.connection import BlockchainConnection
from utils.config import NETWORKS
from contracts.token_interface import TOKEN_ABI
from contracts.bridge_interface import BRIDGE_ABI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("SimulatorEngine")


def simulate_bridge_and_swap(source_network: str, target_network: str, amount_tokens: float):
    if source_network not in NETWORKS or target_network not in NETWORKS:
        logger.error(f"Rede inválida. Disponíveis: {list(NETWORKS.keys())}")
        return

    token_addr = NETWORKS[source_network].get("token_contract")
    bridge_addr = NETWORKS[source_network].get("bridge_contract")

    if not token_addr or not bridge_addr or "0x00000000" in token_addr or "0x00000000" in bridge_addr:
        logger.error(f"Endereços dos contratos não configurados no .env para {source_network}!")
        return

    conn = BlockchainConnection(source_network)
    w3 = conn.get_web3()
    account = w3.eth.account.from_key(conn.private_key)

    checksum_token = w3.to_checksum_address(token_addr)
    checksum_bridge = w3.to_checksum_address(bridge_addr)

    token_contract = w3.eth.contract(address=checksum_token, abi=TOKEN_ABI)
    bridge_contract = w3.eth.contract(address=checksum_bridge, abi=BRIDGE_ABI)

    amount_wei = w3.to_wei(amount_tokens, "ether")
    source_chain_id = NETWORKS[source_network]["chain_id"]
    target_chain_id = NETWORKS[target_network]["chain_id"]
    safe_gas_price = int(w3.eth.gas_price * 2)

    # 1. Passo: Aprovação ERC-20 (Approve)
    current_allowance = token_contract.functions.allowance(account.address, checksum_bridge).call()
    if current_allowance < amount_wei:
        logger.info(f"1. A aprovar {amount_tokens} bTEST para o contrato de Bridge em {source_network}...")
        approve_tx = token_contract.functions.approve(checksum_bridge, amount_wei).build_transaction({
            "chainId": source_chain_id,
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gasPrice": safe_gas_price,
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, conn.private_key)
        tx_approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        w3.eth.wait_for_transaction_receipt(tx_approve_hash)
        logger.info(f"[✓] Aprovação confirmada! Hash: {tx_approve_hash.hex()}")

        while token_contract.functions.allowance(account.address, checksum_bridge).call() < amount_wei:
            logger.info("A aguardar sincronização do allowance no nó RPC...")
            time.sleep(2)
    else:
        logger.info("1. Allowance já aprovado anteriormente. A avançar para o trancamento...")

    # 2. Passo: Execução do Bridge (bridgeTokens)
    logger.info(f"2. A trancar {amount_tokens} bTEST com destino à rede {target_network} (Chain ID: {target_chain_id})...")
    bridge_tx = bridge_contract.functions.bridgeTokens(checksum_token, amount_wei, target_chain_id).build_transaction({
        "chainId": source_chain_id,
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gasPrice": safe_gas_price,
    })
    signed_bridge = w3.eth.account.sign_transaction(bridge_tx, conn.private_key)
    tx_bridge_hash = w3.eth.send_raw_transaction(signed_bridge.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_bridge_hash)
    logger.info(f"[✓] Tokens trancados na Bridge com sucesso! Hash: {tx_bridge_hash.hex()}")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "sepolia_testnet"
    dst = sys.argv[2] if len(sys.argv) > 2 else "arbitrum_sepolia"
    amt = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    simulate_bridge_and_swap(src, dst, amt)