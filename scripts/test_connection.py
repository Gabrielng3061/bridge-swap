import os
import sys

# Garante que o Python encontra os módulos das pastas core e utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.connection import BlockchainConnection
from utils.config import NETWORKS


def test_all_connections():
    print("--- TESTE DE CONEXÃO MULTI-REDE (PORTALDOT & OUTRAS) ---\n")

    for network_name in NETWORKS:
        print(f"=== Testando Rede: {network_name} ===")
        try:
            # Instancia a conexão com a rede iterada
            conn = BlockchainConnection(network_name)
            w3 = conn.get_web3()

            print(f"[✓] Conectado com sucesso ao RPC: {conn.rpc_url}")

            if conn.private_key:
                account = w3.eth.account.from_key(conn.private_key)
                wallet_address = account.address
                print(f"[✓] Carteira carregada: {wallet_address}")

                # Consulta saldo de tokens nativos
                balance_wei = w3.eth.get_balance(wallet_address)
                balance_eth = w3.from_wei(balance_wei, "ether")
                print(f"[i] Saldo atual: {balance_eth} Tokens Nativos")
            else:
                print("[!] PRIVATE_KEY não encontrada no ficheiro .env")

        except Exception as e:
            print(f"[✗] Falha ao conectar/interagir na rede '{network_name}': {e}")

        print("-" * 55)


if __name__ == "__main__":
    test_all_connections()