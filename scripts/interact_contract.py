import os
import sys
import json
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from web3 import Web3
from core.connection import BlockchainConnection
from utils.config import NETWORKS
from contracts.bridge_interface import BRIDGE_ABI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_ARTIFACT = PROJECT_ROOT / "artifacts" / "BridgeSwap.json"


def _load_bridge_abi():
    if BRIDGE_ARTIFACT.exists():
        try:
            payload = json.loads(BRIDGE_ARTIFACT.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("abi"):
                return payload["abi"]
        except Exception:
            pass
    return BRIDGE_ABI


def _safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def interact_with_network(network_name: str):
    print(f"--- INTERAÇÃO COM CONTRATO NA REDE: {network_name} ---")

    try:
        conn = BlockchainConnection(network_name)
        w3 = conn.get_web3()
    except Exception as e:
        print(f"[✗] Não foi possível conectar à rede {network_name}: {e}")
        return

    raw_address = NETWORKS[network_name].get("bridge_contract")
    token_address = NETWORKS[network_name].get("token_contract")

    if not raw_address or "0x00000000" in raw_address.lower():
        print(f"[!] Contrato de Bridge ainda não configurado para a rede {network_name}.")
        print("Execute o deploy.py e cole o endereço no seu arquivo .env.")
        return

    contract_address = Web3.to_checksum_address(raw_address)
    code_bytes = w3.eth.get_code(contract_address)
    if not code_bytes or code_bytes == b"\x00":
        print(f"[!] Nenhum bytecode encontrado em {contract_address} na rede {network_name}.")
        return

    abi = _load_bridge_abi()
    bridge_contract = w3.eth.contract(address=contract_address, abi=abi)

    owner = _safe_call(lambda: bridge_contract.functions.owner().call(), "N/D")
    is_paused = _safe_call(lambda: bridge_contract.functions.paused().call(), None)
    max_op_wei = _safe_call(lambda: bridge_contract.functions.maxOperationAmount().call(), None)

    print(f"[✓] Contrato instanciado com sucesso em: {contract_address}")
    print(f"[i] Proprietário (Owner): {owner}")

    if is_paused is not None:
        print(f"[i] Estado pausado (Paused): {is_paused}")
    else:
        print("[i] Estado pausado (Paused): não suportado neste contrato/ABI")

    if max_op_wei is not None:
        limit_label = (
            "Sem limite (0)"
            if max_op_wei == 0
            else f"{w3.from_wei(max_op_wei, 'ether')} tokens"
        )
        print(f"[i] Limite máximo por operação: {limit_label}")
    else:
        print("[i] Limite máximo por operação: não suportado neste contrato/ABI")

    if token_address and "0x00000000" not in token_address.lower():
        locked = _safe_call(
            lambda: bridge_contract.functions.lockedLiquidity(
                Web3.to_checksum_address(token_address)
            ).call(),
            None,
        )
        if locked is not None:
            print(f"[i] Liquidez bloqueada do Token: {w3.from_wei(locked, 'ether')} tokens")
        else:
            print("[i] Liquidez bloqueada do Token: não disponível neste contrato/ABI")
    print()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "sepolia_testnet"
    interact_with_network(target)