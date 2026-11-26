from pathlib import Path
import pytest
from solcx import compile_source, install_solc

w3_module = pytest.importorskip("web3")
from web3 import Web3

eth_tester_module = pytest.importorskip("eth_tester")
from eth_tester import EthereumTester, PyEVMBackend
from web3.providers.eth_tester import EthereumTesterProvider


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_CONTRACT_PATH = PROJECT_ROOT / "contracts" / "BridgeSwap.sol"
OZ_DIR = PROJECT_ROOT / "node_modules" / "@openzeppelin" / "contracts"


@pytest.fixture(scope="session")
def compiled_contracts():
    install_solc("0.8.20", show_progress=False)

    bridge_source = BRIDGE_CONTRACT_PATH.read_text(encoding="utf-8")
    mock_erc20_source = """
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract MockERC20 is ERC20 {
    constructor(string memory name_, string memory symbol_, uint256 initialSupply)
        ERC20(name_, symbol_)
    {
        _mint(msg.sender, initialSupply);
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
"""
    combined_source = bridge_source + "\n\n" + mock_erc20_source
    compiled = compile_source(
        combined_source,
        output_values=["abi", "bin"],
        solc_version="0.8.20",
        import_remappings=[f"@openzeppelin/contracts={OZ_DIR.as_posix()}"],
        allow_paths=[OZ_DIR.as_posix()],
    )
    return {
        "BridgeSwap": compiled["<stdin>:BridgeSwap"],
        "MockERC20": compiled["<stdin>:MockERC20"],
    }


@pytest.fixture
def chain_env(compiled_contracts):
    tester = EthereumTester(backend=PyEVMBackend())
    w3 = Web3(EthereumTesterProvider(tester))

    owner, new_owner, user, provider, outsider = w3.eth.accounts[:5]
    max_op = 1_000 * 10**18

    token_in_factory = w3.eth.contract(
        abi=compiled_contracts["MockERC20"]["abi"],
        bytecode=compiled_contracts["MockERC20"]["bin"],
    )
    token_out_factory = w3.eth.contract(
        abi=compiled_contracts["MockERC20"]["abi"],
        bytecode=compiled_contracts["MockERC20"]["bin"],
    )

    tx_hash_in = token_in_factory.constructor("Token In", "TIN", 10_000_000 * 10**18).transact(
        {"from": owner}
    )
    token_in_addr = w3.eth.wait_for_transaction_receipt(tx_hash_in)["contractAddress"]
    token_in = w3.eth.contract(address=token_in_addr, abi=compiled_contracts["MockERC20"]["abi"])

    tx_hash_out = token_out_factory.constructor("Token Out", "TOUT", 10_000_000 * 10**18).transact(
        {"from": owner}
    )
    token_out_addr = w3.eth.wait_for_transaction_receipt(tx_hash_out)["contractAddress"]
    token_out = w3.eth.contract(
        address=token_out_addr, abi=compiled_contracts["MockERC20"]["abi"]
    )

    bridge_factory = w3.eth.contract(
        abi=compiled_contracts["BridgeSwap"]["abi"],
        bytecode=compiled_contracts["BridgeSwap"]["bin"],
    )
    tx_hash_bridge = bridge_factory.constructor(owner, max_op).transact({"from": owner})
    bridge_addr = w3.eth.wait_for_transaction_receipt(tx_hash_bridge)["contractAddress"]
    bridge = w3.eth.contract(address=bridge_addr, abi=compiled_contracts["BridgeSwap"]["abi"])

    # Distribui saldos iniciais para testes
    token_in.functions.mint(user, 500_000 * 10**18).transact({"from": owner})
    token_out.functions.mint(provider, 500_000 * 10**18).transact({"from": owner})

    # Habilita cadeia de destino 421614 (Arbitrum Sepolia) por padrão no fixture
    bridge.functions.setTargetChainAllowed(421614, True).transact({"from": owner})

    return {
        "w3": w3,
        "owner": owner,
        "new_owner": new_owner,
        "user": user,
        "provider": provider,
        "outsider": outsider,
        "token_in": token_in,
        "token_out": token_out,
        "bridge": bridge,
        "max_op": max_op,
    }


def test_two_step_ownership_transfer(chain_env):
    bridge = chain_env["bridge"]
    owner = chain_env["owner"]
    new_owner = chain_env["new_owner"]
    outsider = chain_env["outsider"]

    assert bridge.functions.owner().call() == owner

    # Inicia transferência para new_owner: owner ainda não muda antes de aceitar
    bridge.functions.transferOwnership(new_owner).transact({"from": owner})
    assert bridge.functions.owner().call() == owner
    assert bridge.functions.pendingOwner().call() == new_owner

    # Terceiro não consegue aceitar
    with pytest.raises(Exception):
        bridge.functions.acceptOwnership().transact({"from": outsider})

    # Novo owner aceita e assume o controle
    bridge.functions.acceptOwnership().transact({"from": new_owner})
    assert bridge.functions.owner().call() == new_owner


def test_pause_and_unpause_blocks_bridge_and_swap(chain_env):
    bridge = chain_env["bridge"]
    owner = chain_env["owner"]
    user = chain_env["user"]
    provider = chain_env["provider"]
    token_in = chain_env["token_in"]
    token_out = chain_env["token_out"]

    amount = 100 * 10**18
    token_out.functions.approve(bridge.address, amount).transact({"from": provider})
    bridge.functions.depositSwapLiquidity(token_out.address, amount).transact({"from": provider})

    token_in.functions.approve(bridge.address, amount * 2).transact({"from": user})

    # Pausa o contrato
    bridge.functions.pause().transact({"from": owner})
    assert bridge.functions.paused().call() is True

    with pytest.raises(Exception):
        bridge.functions.bridgeTokens(token_in.address, amount, 421614).transact({"from": user})

    with pytest.raises(Exception):
        bridge.functions.swapTokens(token_in.address, token_out.address, amount, 1).transact(
            {"from": user}
        )

    # Despausa e confirma que volta a funcionar
    bridge.functions.unpause().transact({"from": owner})
    assert bridge.functions.paused().call() is False

    bridge.functions.bridgeTokens(token_in.address, amount, 421614).transact({"from": user})
    assert bridge.functions.lockedLiquidity(token_in.address).call() == amount


def test_max_operation_amount_enforced_and_updatable(chain_env):
    bridge = chain_env["bridge"]
    owner = chain_env["owner"]
    user = chain_env["user"]
    token_in = chain_env["token_in"]
    max_op = chain_env["max_op"]

    over_limit = max_op + 1
    token_in.functions.approve(bridge.address, over_limit * 2).transact({"from": user})

    # Acima do limite reverte
    with pytest.raises(Exception):
        bridge.functions.bridgeTokens(token_in.address, over_limit, 421614).transact({"from": user})

    # Dentro do limite passa
    bridge.functions.bridgeTokens(token_in.address, max_op, 421614).transact({"from": user})
    assert bridge.functions.lockedLiquidity(token_in.address).call() == max_op

    # Owner aumenta o limite e operação anterior passa
    new_limit = max_op * 5
    bridge.functions.setMaxOperationAmount(new_limit).transact({"from": owner})
    bridge.functions.bridgeTokens(token_in.address, over_limit, 421614).transact({"from": user})
    assert bridge.functions.lockedLiquidity(token_in.address).call() == max_op + over_limit


def test_allowed_target_chains_validation(chain_env):
    bridge = chain_env["bridge"]
    owner = chain_env["owner"]
    user = chain_env["user"]
    token_in = chain_env["token_in"]

    disallowed_chain = 84532  # Base Sepolia ainda não habilitada
    amount = 50 * 10**18
    token_in.functions.approve(bridge.address, amount * 2).transact({"from": user})

    with pytest.raises(Exception):
        bridge.functions.bridgeTokens(token_in.address, amount, disallowed_chain).transact(
            {"from": user}
        )

    bridge.functions.setTargetChainAllowed(disallowed_chain, True).transact({"from": owner})
    bridge.functions.bridgeTokens(token_in.address, amount, disallowed_chain).transact(
        {"from": user}
    )
    assert bridge.functions.lockedLiquidity(token_in.address).call() == amount


def test_liquidity_accounting_and_emergency_withdraw(chain_env):
    bridge = chain_env["bridge"]
    owner = chain_env["owner"]
    user = chain_env["user"]
    provider = chain_env["provider"]
    token_in = chain_env["token_in"]
    token_out = chain_env["token_out"]

    liq_amount = 500 * 10**18
    swap_in = 100 * 10**18
    # Taxa de 0.20% (20 bps) -> 99.80% de saída
    expected_out = (swap_in * (10_000 - 20)) // 10_000

    token_out.functions.approve(bridge.address, liq_amount).transact({"from": provider})
    bridge.functions.depositSwapLiquidity(token_out.address, liq_amount).transact({"from": provider})
    assert bridge.functions.swapLiquidity(token_out.address).call() == liq_amount

    token_in.functions.approve(bridge.address, swap_in).transact({"from": user})
    bridge.functions.swapTokens(
        token_in.address, token_out.address, swap_in, expected_out
    ).transact({"from": user})

    assert bridge.functions.swapLiquidity(token_out.address).call() == liq_amount - expected_out
    assert bridge.functions.swapLiquidity(token_in.address).call() == swap_in
    assert token_out.functions.balanceOf(user).call() == expected_out

    # emergencyWithdraw exige contrato pausado
    with pytest.raises(Exception):
        bridge.functions.emergencyWithdraw(token_out.address, 10 * 10**18).transact({"from": owner})

    bridge.functions.pause().transact({"from": owner})
    remaining_swap_liq = bridge.functions.swapLiquidity(token_out.address).call()

    # Tentar sacar acima do saldo do contrato deve reverter
    with pytest.raises(Exception):
        bridge.functions.emergencyWithdraw(
            token_out.address, remaining_swap_liq + (25 * 10**18)
        ).transact({"from": owner})

    # Sacar todo o saldo disponível de swapLiquidity deve passar e zerar o pool
    bridge.functions.emergencyWithdraw(token_out.address, remaining_swap_liq).transact(
        {"from": owner}
    )
    assert bridge.functions.swapLiquidity(token_out.address).call() == 0
    assert token_out.functions.balanceOf(owner).call() >= remaining_swap_liq


def test_swap_reverts_when_slippage_exceeded(chain_env):
    bridge = chain_env["bridge"]
    user = chain_env["user"]
    provider = chain_env["provider"]
    token_in = chain_env["token_in"]
    token_out = chain_env["token_out"]

    liq_amount = 500 * 10**18
    swap_in = 100 * 10**18
    expected_out = (swap_in * (10_000 - 20)) // 10_000
    too_high_min_out = expected_out + 1

    token_out.functions.approve(bridge.address, liq_amount).transact({"from": provider})
    bridge.functions.depositSwapLiquidity(token_out.address, liq_amount).transact({"from": provider})

    token_in.functions.approve(bridge.address, swap_in).transact({"from": user})

    with pytest.raises(Exception):
        bridge.functions.swapTokens(
            token_in.address, token_out.address, swap_in, too_high_min_out
        ).transact({"from": user})


def test_only_owner_can_call_admin_functions(chain_env):
    bridge = chain_env["bridge"]
    outsider = chain_env["outsider"]
    new_owner = chain_env["new_owner"]
    token_out = chain_env["token_out"]

    with pytest.raises(Exception):
        bridge.functions.pause().transact({"from": outsider})

    with pytest.raises(Exception):
        bridge.functions.unpause().transact({"from": outsider})

    with pytest.raises(Exception):
        bridge.functions.setTargetChainAllowed(84532, True).transact({"from": outsider})

    with pytest.raises(Exception):
        bridge.functions.setMaxOperationAmount(100 * 10**18).transact({"from": outsider})

    with pytest.raises(Exception):
        bridge.functions.withdrawSwapLiquidity(token_out.address, 1).transact({"from": outsider})

    with pytest.raises(Exception):
        bridge.functions.transferOwnership(new_owner).transact({"from": outsider})

    with pytest.raises(Exception):
        bridge.functions.emergencyWithdraw(token_out.address, 1).transact({"from": outsider})