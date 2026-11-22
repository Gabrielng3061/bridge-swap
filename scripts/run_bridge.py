import os
import sys
import json
import time
import logging
import threading

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.connection import BlockchainConnection
from utils.config import NETWORKS
from contracts.bridge_interface import BRIDGE_ABI
from contracts.token_interface import TOKEN_ABI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("EVMRelayer")

CHAIN_ID_MAP = {
    11155111: "sepolia_testnet",
    421614: "arbitrum_sepolia",
    84532: "base_sepolia",
    80002: "polygon_amoy",
}

CONFIRMATION_OFFSETS = {
    "sepolia_testnet": 1,
    "arbitrum_sepolia": 0,
    "base_sepolia": 0,
    "polygon_amoy": 0,
}

PROCESSED_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "processed_txs.json"))
state_lock = threading.Lock()
MAX_BLOCK_SPAN = 2000  # Limite seguro por consulta get_logs em RPCs públicos


def load_processed_txs() -> set:
    with state_lock:
        if not os.path.exists(PROCESSED_FILE):
            return set()
        try:
            with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(item.lower() for item in data if isinstance(data, list))
        except Exception as e:
            logger.warning(f"Falha ao ler {PROCESSED_FILE}, iniciando conjunto vazio: {e}")
            return set()


def save_processed_tx(tx_hash: str):
    normalized = tx_hash.lower()
    with state_lock:
        os.makedirs(os.path.dirname(PROCESSED_FILE), exist_ok=True)
        existing = set()
        if os.path.exists(PROCESSED_FILE):
            try:
                with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        existing = set(item.lower() for item in data)
            except Exception:
                existing = set()
        existing.add(normalized)
        with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(existing), f, indent=2)


def execute_destination_delivery(target_network: str, recipient: str, amount_wei: int, source_tx_hash: str):
    target_token_addr = NETWORKS.get(target_network, {}).get("token_contract")

    if not target_token_addr or "0x00000000" in target_token_addr:
        logger.error(f"Contrato de token não configurado no .env para {target_network}.")
        return False

    conn = BlockchainConnection(target_network)
    w3 = conn.get_web3()
    relayer_account = w3.eth.account.from_key(conn.private_key)

    token_contract = w3.eth.contract(
        address=w3.to_checksum_address(target_token_addr),
        abi=TOKEN_ABI
    )

    safe_gas_price = int(w3.eth.gas_price * 2)

    logger.info(
        f"[{target_network}] A entregar {w3.from_wei(amount_wei, 'ether')} bTEST para {recipient} "
        f"(Ref. origem: {source_tx_hash})..."
    )

    tx = token_contract.functions.transfer(
        w3.to_checksum_address(recipient),
        amount_wei
    ).build_transaction({
        "chainId": NETWORKS[target_network]["chain_id"],
        "from": relayer_account.address,
        "nonce": w3.eth.get_transaction_count(relayer_account.address),
        "gasPrice": safe_gas_price,
    })

    signed_tx = w3.eth.account.sign_transaction(tx, conn.private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    if receipt.status == 1:
        logger.info(f"[{target_network}] [✓] Tokens entregues! Hash destino: {receipt.transactionHash.hex()}")
        return True
    else:
        logger.error(f"[{target_network}] [✗] Transação de entrega falhou! Hash: {receipt.transactionHash.hex()}")
        return False


def _is_beyond_head_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "-32602" in msg and ("beyond current head block" in msg or "block range" in msg)


def get_logs_in_range(event_obj, from_block: int, to_block: int):
    """Consulta logs dividindo em janelas menores e recuando se o RPC pedir bloco além do head."""
    if from_block > to_block:
        return [], to_block

    events = []
    current_from = from_block
    last_safe_to = from_block - 1

    while current_from <= to_block:
        current_to = min(current_from + MAX_BLOCK_SPAN - 1, to_block)
        try:
            chunk = event_obj.get_logs(from_block=current_from, to_block=current_to)
            events.extend(chunk)
            last_safe_to = current_to
            current_from = current_to + 1
        except Exception as e:
            if _is_beyond_head_error(e):
                logger.debug(f"RPC reportou head menor que {current_to}; aguardando próximo ciclo para avançar.")
                break
            raise

    return events, last_safe_to


def watch_network_events(source_network: str):
    logger.info(f"--- A iniciar listener na origem: {source_network} ---")

    conn = BlockchainConnection(source_network)
    w3 = conn.get_web3()

    contract_addr = NETWORKS[source_network].get("bridge_contract")
    if not contract_addr or "0x00000000" in contract_addr:
        logger.warning(f"Bridge não configurada no .env para {source_network}. Ignorando...")
        return

    bridge_contract = w3.eth.contract(
        address=w3.to_checksum_address(contract_addr),
        abi=BRIDGE_ABI
    )

    confirmation_offset = CONFIRMATION_OFFSETS.get(source_network, 0)
    last_checked_block = w3.eth.block_number
    logger.info(f"[{source_network}] Escutando eventos 'TokensBridged' a partir do bloco {last_checked_block}...")

    while True:
        try:
            latest_block = w3.eth.block_number
            safe_head = max(0, latest_block - confirmation_offset)

            if safe_head > last_checked_block:
                from_block = last_checked_block + 1
                to_block = safe_head

                events, last_safe_to = get_logs_in_range(bridge_contract.events.TokensBridged, from_block, to_block)
                processed_txs = load_processed_txs()

                for event in events:
                    source_tx_hash = event["transactionHash"].hex()
                    if source_tx_hash.lower() in processed_txs:
                        logger.info(f"[{source_network}] Evento {source_tx_hash} já processado anteriormente. Ignorando.")
                        continue

                    sender = event["args"]["sender"]
                    amount = event["args"]["amount"]
                    target_chain_id = event["args"]["targetChainId"]
                    target_network = CHAIN_ID_MAP.get(target_chain_id)

                    logger.info(f"[!] NOVO BRIDGE DETETADO na {source_network}!")
                    logger.info(f"    Utilizador: {sender} | Valor: {w3.from_wei(amount, 'ether')} bTEST")
                    logger.info(f"    Destino: {target_network} (Chain ID: {target_chain_id})")

                    if target_network:
                        ok = execute_destination_delivery(target_network, sender, amount, source_tx_hash)
                        if ok:
                            save_processed_tx(source_tx_hash)
                    else:
                        logger.warning(f"[{source_network}] Chain ID de destino {target_chain_id} não mapeado.")

                # Avança apenas até o último intervalo confirmado sem erro
                if last_safe_to >= from_block:
                    last_checked_block = last_safe_to

            time.sleep(3)
        except Exception as e:
            logger.error(f"[{source_network}] Erro no ciclo do Relayer: {e}")
            time.sleep(5)


def start_multi_chain_relayer():
    active_networks = [
        net_name for net_name, cfg in NETWORKS.items()
        if cfg.get("bridge_contract") and "0x00000000" not in cfg.get("bridge_contract")
    ]

    if not active_networks:
        logger.error("Nenhuma rede com 'bridge_contract' válido encontrada no .env.")
        return

    logger.info(f"Redes ativas para escuta: {', '.join(active_networks)}")

    threads = []
    for net_name in active_networks:
        t = threading.Thread(target=watch_network_events, args=(net_name,), daemon=True, name=f"Listener-{net_name}")
        t.start()
        threads.append(t)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Encerrando Relayer multi-chain...")


if __name__ == "__main__":
    start_multi_chain_relayer()