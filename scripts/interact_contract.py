import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from web3 import Web3
from core.connection import BlockchainConnection
from utils.config import NETWORKS
from contracts.bridge_interface import BRIDGE_ABI


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

    if not raw_address or "0x00000000" in raw_address:
        print(f"[!] Contrato de Bridge ainda não configurado para a rede {network_name}.")
        print("Execute o deploy.py e cole o endereço no seu ficheiro .env.")
        return

    contract_address = Web3.to_checksum_address(raw_address)
    bridge_contract = w3.eth.contract(address=contract_address, abi=BRIDGE_ABI)

    owner = bridge_contract.functions.owner().call()
    print(f"[✓] Contrato instanciado com sucesso em: {contract_address}")
    print(f"[i] Proprietário (Owner) do contrato: {owner}")

    if token_address and "0x00000000" not in token_address:
        locked = bridge_contract.functions.lockedLiquidity(Web3.to_checksum_address(token_address)).call()
        print(f"[i] Liquidez bloqueada do Token: {w3.from_wei(locked, 'ether')} bTEST\n")


if __name__ == "__main__":
    interact_with_network("sepolia_testnet")