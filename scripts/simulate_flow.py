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


def _send_and_wait(w3, tx: dict, private_key: str, label: str):
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    raw_tx = getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction")
    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    logger.info(f"[{label}] Tx enviada: {tx_hash.hex()} — aguardando confirmação...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status != 1:
        raise RuntimeError(f"[{label}] Transação falhou on-chain (status=0). Hash: {tx_hash.hex()}")
    return receipt


def simulate_bridge_and_swap(source_network: str, target_network: str, amount_tokens: float):
    if source_network not in NETWORKS or target_network not in NETWORKS:
        logger.error(f"Rede inválida. Disponíveis: {list(NETWORKS.keys())}")
        return

    token_addr = NETWORKS[source_network].get("token_contract")
    bridge_addr = NETWORKS[source_network].get("bridge_contract")

    if (
        not token_addr
        or not bridge_addr
        or "0x00000000" in token_addr.lower()
        or "0x00000000" in bridge_addr.lower()
    ):
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
        logger.info(f"1. Aprovando {amount_tokens} tokens para o Bridge em {source_network}...")
        approve_tx = token_contract.functions.approve(checksum_bridge, amount_wei).build_transaction({
            "chainId": source_chain_id,
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            "gasPrice": safe_gas_price,
        })
        approve_receipt = _send_and_wait(w3, approve_tx, conn.private_key, "approve")
        logger.info(f"[✓] Aprovação confirmada! Hash: {approve_receipt.transactionHash.hex()}")

        for _ in range(15):
            if token_contract.functions.allowance(account.address, checksum_bridge).call() >= amount_wei:
                break
            logger.info("Aguardando sincronização do allowance no nó RPC...")
            time.sleep(2)
    else:
        logger.info("1. Allowance já aprovado anteriormente. Avançando para o bridge...")

    # 2. Passo: Execução do Bridge (bridgeTokens)
    logger.info(
        f"2. Bloqueando {amount_tokens} tokens com destino à rede {target_network} "
        f"(Chain ID: {target_chain_id})..."
    )
    bridge_tx = bridge_contract.functions.bridgeTokens(
        checksum_token, amount_wei, target_chain_id
    ).build_transaction({
        "chainId": source_chain_id,
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, "pending"),
        "gasPrice": safe_gas_price,
    })
    bridge_receipt = _send_and_wait(w3, bridge_tx, conn.private_key, "bridgeTokens")
    logger.info(f"[✓] Tokens bloqueados na Bridge com sucesso! Hash: {bridge_receipt.transactionHash.hex()}")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "sepolia_testnet"
    dst = sys.argv[2] if len(sys.argv) > 2 else "arbitrum_sepolia"
    amt = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    simulate_bridge_and_swap(src, dst, amt)