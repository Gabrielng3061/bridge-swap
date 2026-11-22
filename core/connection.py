import logging
from web3 import Web3
from utils.config import NETWORKS, PRIVATE_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("BlockchainConnection")


class BlockchainConnection:
    """Gerencia a conexão com qualquer rede EVM."""

    def __init__(self, network_name: str) -> None:
        if network_name not in NETWORKS:
            raise ValueError(f"Rede {network_name} não configurada no config.py")

        self.rpc_url = NETWORKS[network_name]["rpc"]
        self.private_key = PRIVATE_KEY
        self.w3 = self._initialize_connection(network_name)

    def _initialize_connection(self, network_name: str) -> Web3:
        logger.info(f"A conectar à rede {network_name}...")
        w3 = Web3(Web3.HTTPProvider(self.rpc_url))

        if not w3.is_connected():
            logger.error(f"Falha ao conectar à rede {network_name}.")
            raise ConnectionError(f"Sem ligação a {network_name}.")

        logger.info(f"Conexão a {network_name} estabelecida!")
        return w3

    def get_web3(self) -> Web3:
        return self.w3