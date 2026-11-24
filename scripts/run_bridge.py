import os
import sys
import json
import time
import atexit
import signal
import tempfile
import logging
import threading
from typing import Any, Callable, TypeVar

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from web3.exceptions import Web3RPCError
from core.connection import BlockchainConnection
from utils.config import NETWORKS
from contracts.bridge_interface import BRIDGE_ABI
from contracts.token_interface import TOKEN_ABI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("EVMRelayer")

T = TypeVar("T")

CHAIN_ID_MAP = {
    cfg["chain_id"]: net_name
    for net_name, cfg in NETWORKS.items()
    if cfg.get("chain_id") is not None
}

CONFIRMATION_OFFSETS = {
    "sepolia_testnet": 1,
    "arbitrum_sepolia": 0,
    "base_sepolia": 0,
    "polygon_amoy": 0,
}

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROCESSED_FILE = os.path.join(DATA_DIR, "processed_txs.json")
STATE_FILE = os.path.join(DATA_DIR, "relayer_state.json")
LOCK_FILE = os.path.join(DATA_DIR, "relayer.lock")

state_lock = threading.Lock()
stop_event = threading.Event()
MAX_BLOCK_SPAN = 2000


def retry_rpc(
    fn: Callable[[], T],
    retries: int = 4,
    base_delay: float = 0.8,
    max_delay: float = 8.0,
    label: str = "RPC",
) -> T:
    """Executa chamadas RPC com backoff exponencial em falhas transitórias."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except (Web3RPCError, TimeoutError, ConnectionError, OSError, ValueError) as exc:
            last_exc = exc
            if attempt == retries:
                break
            sleep_for = min(max_delay, base_delay * (2**attempt))
            logger.warning(f"[{label}] Falha transitória ({exc}); nova tentativa em {sleep_for:.1f}s...")
            time.sleep(sleep_for)
    assert last_exc is not None
    raise last_exc


def _atomic_write_json(target_path: str, payload: Any) -> None:
    """Escreve JSON de forma atômica via arquivo temporário + os.replace."""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(target_path), prefix=".tmp_portaldot_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(payload, tmp_file, indent=2)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def acquire_instance_lock() -> None:
    """Impede que duas instâncias do relayer rodem ao mesmo tempo."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except FileExistsError:
        existing_pid = None
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                existing_pid = int(f.read().strip())
        except Exception:
            pass

        if existing_pid and existing_pid != os.getpid():
            try:
                os.kill(existing_pid, 0)
                raise RuntimeError(f"Já existe uma instância do Relayer ativa (PID {existing_pid}).")
            except ProcessLookupError:
                logger.warning(f"Lock órfão encontrado (PID {existing_pid}); substituindo...")
                os.remove(LOCK_FILE)
                acquire_instance_lock()
            except PermissionError:
                raise RuntimeError(f"Já existe uma instância do Relayer ativa (PID {existing_pid}).")
        else:
            raise RuntimeError("Já existe uma instância do Relayer ativa.")


def release_instance_lock() -> None:
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                pid_str = f.read().strip()
            if pid_str == str(os.getpid()):
                os.remove(LOCK_FILE)
        except OSError:
            pass


def load_processed_txs() -> set:
    with state_lock:
        if not os.path.exists(PROCESSED_FILE):
            return set()
        try:
            with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {str(item).lower() for item in data if isinstance(data, list)}
        except Exception as e:
            logger.warning(f"Falha ao ler {PROCESSED_FILE}, iniciando conjunto vazio: {e}")
            return set()


def save_processed_tx(tx_hash: str) -> None:
    normalized = tx_hash.lower()
    with state_lock:
        existing = set()
        if os.path.exists(PROCESSED_FILE):
            try:
                with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        existing = {str(item).lower() for item in data}
            except Exception:
                existing = set()
        existing.add(normalized)
        _atomic_write_json(PROCESSED_FILE, sorted(existing))


def load_last_checked_block(network_name: str) -> int | None:
    with state_lock:
        if not os.path.exists(STATE_FILE):
            return None
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and network_name in data:
                    val = int(data[network_name])
                    return max(0, val)
        except Exception as e:
            logger.warning(f"Falha ao ler cursor de bloco em {STATE_FILE}: {e}")
        return None


def save_last_checked_block(network_name: str, block_number: int) -> None:
    with state_lock:
        current: dict[str, int] = {}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, dict):
                        current = {str(k): int(v) for k, v in raw.items()}
            except Exception:
                current = {}
        current[network_name] = int(block_number)
        _atomic_write_json(STATE_FILE, current)


def _is_valid_contract_addr(addr: str | None) -> bool:
    return bool(addr and addr != "0x..." and "0x0000000000000000000000000000000000000000" not in addr.lower())


def execute_destination_delivery(target_network: str, recipient: str, amount_wei: int, source_tx_hash: str) -> bool:
    target_cfg = NETWORKS.get(target_network, {})
    target_token_addr = target_cfg.get("token_contract")

    if not _is_valid_contract_addr(target_token_addr):
        logger.error(f"Contrato de token não configurado no .env para {target_network}.")
        return False

    if amount_wei <= 0:
        logger.warning(f"[{target_network}] Valor inválido ({amount_wei}) na tx {source_tx_hash}. Ignorando.")
        return False

    conn = BlockchainConnection(target_network)
    w3 = conn.get_web3()
    relayer_account = w3.eth.account.from_key(conn.private_key)

    token_contract = w3.eth.contract(
        address=w3.to_checksum_address(target_token_addr),
        abi=TOKEN_ABI,
    )
    checksum_recipient = w3.to_checksum_address(recipient)

    logger.info(
        f"[{target_network}] A entregar {w3.from_wei(amount_wei, 'ether')} bTEST para {checksum_recipient} "
        f"(Ref. origem: {source_tx_hash})..."
    )

    gas_multiplier = 2.0
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            nonce = retry_rpc(
                lambda: w3.eth.get_transaction_count(relayer_account.address, "pending"),
                label=f"{target_network}:nonce",
            )
            base_gas = retry_rpc(lambda: w3.eth.gas_price, label=f"{target_network}:gas_price")
            safe_gas_price = int(base_gas * gas_multiplier)

            tx = token_contract.functions.transfer(
                checksum_recipient,
                amount_wei,
            ).build_transaction({
                "chainId": target_cfg["chain_id"],
                "from": relayer_account.address,
                "nonce": nonce,
                "gasPrice": safe_gas_price,
            })

            signed_tx = w3.eth.account.sign_transaction(tx, conn.private_key)
            raw_tx = getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction")
            tx_hash = retry_rpc(lambda: w3.eth.send_raw_transaction(raw_tx), label=f"{target_network}:send_tx")
            receipt = retry_rpc(
                lambda: w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180),
                label=f"{target_network}:receipt",
            )

            if receipt.status == 1:
                logger.info(f"[{target_network}] [✓] Tokens entregues! Hash destino: {receipt.transactionHash.hex()}")
                return True

            logger.error(f"[{target_network}] [✗] Transação de entrega falhou (status=0)! Hash: {receipt.transactionHash.hex()}")
            return False

        except Exception as exc:
            msg = str(exc).lower()
            if any(k in msg for k in ("underpriced", "fee too low", "nonce too low", "already known")):
                gas_multiplier *= 1.25
                logger.warning(
                    f"[{target_network}] Ajuste de gás/nonce na tentativa {attempt}/{max_attempts} "
                    f"(multiplicador {gas_multiplier:.2f}x): {exc}"
                )
                continue

            if attempt == max_attempts:
                logger.error(f"[{target_network}] Falha definitiva na entrega da tx {source_tx_hash}: {exc}")
                return False

            backoff = 1.5 * attempt
            logger.warning(f"[{target_network}] Erro na entrega (tentativa {attempt}/{max_attempts}): {exc}. Aguardando {backoff:.1f}s...")
            time.sleep(backoff)

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
            chunk = retry_rpc(
                lambda c_from=current_from, c_to=current_to: event_obj.get_logs(from_block=c_from, to_block=c_to),
                retries=2,
                base_delay=0.5,
                label="get_logs",
            )
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

    contract_addr = NETWORKS[source_network].get("bridge_contract")
    if not _is_valid_contract_addr(contract_addr):
        logger.warning(f"Bridge não configurada no .env para {source_network}. Ignorando...")
        return

    try:
        conn = BlockchainConnection(source_network)
        w3 = conn.get_web3()
    except Exception as e:
        logger.error(f"[{source_network}] Falha inicial de conexão: {e}")
        return

    expected_contract = w3.to_checksum_address(contract_addr)
    bridge_contract = w3.eth.contract(address=expected_contract, abi=BRIDGE_ABI)

    confirmation_offset = CONFIRMATION_OFFSETS.get(source_network, 0)
    saved_cursor = load_last_checked_block(source_network)
    current_head = retry_rpc(lambda: w3.eth.block_number, label=f"{source_network}:head")

    if saved_cursor is not None and saved_cursor <= current_head:
        last_checked_block = saved_cursor
        logger.info(f"[{source_network}] Retomando cursor salvo em {last_checked_block} (head atual: {current_head})...")
    else:
        last_checked_block = current_head
        logger.info(f"[{source_network}] Escutando eventos 'TokensBridged' a partir do bloco {last_checked_block}...")

    while not stop_event.is_set():
        try:
            if not w3.is_connected():
                w3 = conn.reconnect()
                bridge_contract = w3.eth.contract(address=expected_contract, abi=BRIDGE_ABI)

            latest_block = retry_rpc(lambda: w3.eth.block_number, label=f"{source_network}:latest_block")
            safe_head = max(0, latest_block - confirmation_offset)

            if safe_head > last_checked_block:
                from_block = last_checked_block + 1
                to_block = safe_head

                events, last_safe_to = get_logs_in_range(bridge_contract.events.TokensBridged, from_block, to_block)
                processed_txs = load_processed_txs()

                for event in events:
                    if stop_event.is_set():
                        break

                    event_address = event.get("address", "")
                    if event_address and event_address.lower() != expected_contract.lower():
                        logger.warning(f"[{source_network}] Evento de endereço inesperado ({event_address}). Ignorando.")
                        continue

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

                if last_safe_to >= from_block:
                    last_checked_block = last_safe_to
                    save_last_checked_block(source_network, last_checked_block)

            stop_event.wait(3)
        except Exception as e:
            logger.error(f"[{source_network}] Erro no ciclo do Relayer: {e}")
            stop_event.wait(5)


def _handle_shutdown(signum, frame):
    logger.info(f"Sinal {signum} recebido. Encerrando Relayer multi-chain com segurança...")
    stop_event.set()


def start_multi_chain_relayer():
    acquire_instance_lock()
    atexit.register(release_instance_lock)
    signal.signal(signal.SIGINT, _handle_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_shutdown)

    active_networks = [
        net_name for net_name, cfg in NETWORKS.items()
        if _is_valid_contract_addr(cfg.get("bridge_contract"))
    ]

    if not active_networks:
        logger.error("Nenhuma rede com 'bridge_contract' válido encontrada no .env.")
        release_instance_lock()
        return

    logger.info(f"Redes ativas para escuta: {', '.join(active_networks)}")

    threads = []
    for net_name in active_networks:
        t = threading.Thread(target=watch_network_events, args=(net_name,), daemon=True, name=f"Listener-{net_name}")
        t.start()
        threads.append(t)

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=2)
        release_instance_lock()
        logger.info("Relayer encerrado.")


if __name__ == "__main__":
    start_multi_chain_relayer()