import os
import sys
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import scripts.run_bridge as relayer
from utils.config import NETWORKS


def test_chain_id_map_matches_networks():
    assert relayer.CHAIN_ID_MAP[11155111] == "sepolia_testnet"
    assert relayer.CHAIN_ID_MAP[421614] == "arbitrum_sepolia"
    assert relayer.CHAIN_ID_MAP[84532] == "base_sepolia"
    assert relayer.CHAIN_ID_MAP[80002] == "polygon_amoy"
    for net_name, cfg in NETWORKS.items():
        assert relayer.CHAIN_ID_MAP[cfg["chain_id"]] == net_name


def test_atomic_processed_txs_persistence(tmp_path, monkeypatch):
    tx_file = tmp_path / "processed_txs.json"
    monkeypatch.setattr(relayer, "PROCESSED_FILE", str(tx_file))

    assert relayer.load_processed_txs() == set()

    sample_hash = "0xAbCd1234"
    relayer.save_processed_tx(sample_hash)
    relayer.save_processed_tx(sample_hash.lower())  # idempotência

    loaded = relayer.load_processed_txs()
    assert loaded == {"0xabcd1234"}


def test_persistent_block_cursor(tmp_path, monkeypatch):
    state_file = tmp_path / "relayer_state.json"
    monkeypatch.setattr(relayer, "STATE_FILE", str(state_file))

    assert relayer.load_last_checked_block("polygon_amoy") is None
    relayer.save_last_checked_block("polygon_amoy", 53657100)
    assert relayer.load_last_checked_block("polygon_amoy") == 53657100


def test_instance_lock_prevents_duplicate(tmp_path, monkeypatch):
    lock_file = tmp_path / "relayer.lock"
    monkeypatch.setattr(relayer, "LOCK_FILE", str(lock_file))
    monkeypatch.setattr(relayer, "DATA_DIR", str(tmp_path))

    relayer.acquire_instance_lock()
    assert lock_file.exists()

    with pytest.raises(RuntimeError):
        relayer.acquire_instance_lock()

    relayer.release_instance_lock()
    assert not lock_file.exists()