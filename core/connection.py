import time
import logging
from typing import List
from web3 import Web3
from utils.config import NETWORKS, PRIVATE_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("BlockchainConnection")


class BlockchainConnection:
    """Gerencia a conexão com qualquer rede EVM com suporte a fallback de RPC."""

    def __init__(self, network_name: str, retries: int = 3, retry_delay: float = 1.0) -> None:
        if network_name not in NETWORKS:
            raise ValueError(f"Rede {network_name} não configurada no config.py")

        self.network_name = network_name
        self.retries = retries
        self.retry_delay = retry_delay
        self.rpc_candidates: List[str] = self._build_rpc_candidates(NETWORKS[network_name])
        self.rpc_url: str = self.rpc_candidates[0]
        self.private_key = PRIVATE_KEY
        self.w3 = self._initialize_connection(network_name)

    @staticmethod
    def _build_rpc_candidates(net_cfg: dict) -> List[str]:
        candidates: List[str] = []
        primary = net_cfg.get("rpc")
        if primary:
            candidates.append(primary)

        fallback_rpcs = net_cfg.get("fallback_rpcs") or []
        if isinstance(fallback_rpcs, (list, tuple)):
            for url in fallback_rpcs:
                if url and url not in candidates:
                    candidates.append(url)

        return candidates

    def _initialize_connection(self, network_name: str) -> Web3:
        last_error: Exception | None = None

        for rpc in self.rpc_candidates:
            for attempt in range(1, self.retries + 1):
                try:
                    logger.info(f"A conectar à rede {network_name} via {rpc} (tentativa {attempt}/{self.retries})...")
                    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
                    if w3.is_connected():
                        self.rpc_url = rpc
                        logger.info(f"Conexão a {network_name} estabelecida em {rpc}!")
                        return w3
                except Exception as exc:
                    last_error = exc
                    logger.warning(f"Falha em {rpc} ({network_name}): {exc}")

                if attempt < self.retries:
                    time.sleep(self.retry_delay * attempt)

        logger.error(f"Falha ao conectar à rede {network_name} em todos os RPCs configurados.")
        raise ConnectionError(f"Sem ligação a {network_name}.") from last_error

    def reconnect(self) -> Web3:
        """Tenta restabelecer a conexão caso o RPC atual falhe durante a execução."""
        self.w3 = self._initialize_connection(self.network_name)
        return self.w3

    def get_web3(self) -> Web3:
        return self.w3