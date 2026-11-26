// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable2Step.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/**
 * @title BridgeSwap
 * @dev Contrato modular para operações de Bridge e Swap em redes EVM,
 *      utilizando padrões OpenZeppelin (Ownable2Step, Pausable, ReentrancyGuard, SafeERC20)
 *      e separação de liquidez.
 */
contract BridgeSwap is Ownable2Step, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // Taxa de swap em basis points (20 bps = 0.20%, mantendo 99.80% de saída)
    uint256 public constant SWAP_FEE_BPS = 20;
    uint256 public constant BPS_DENOMINATOR = 10000;

    // Limite máximo por operação de bridge ou swap (0 = sem limite configurado)
    uint256 public maxOperationAmount;

    // Liquidez bloqueada para bridge por token
    mapping(address => uint256) public lockedLiquidity;

    // Liquidez dedicada a swaps por token
    mapping(address => uint256) public swapLiquidity;

    // Redes de destino habilitadas para bridge
    mapping(uint256 => bool) public allowedTargetChains;

    event TokensBridged(
        address indexed sender,
        address indexed token,
        uint256 amount,
        uint256 targetChainId,
        uint256 timestamp
    );

    event TokensSwapped(
        address indexed user,
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 amountIn,
        uint256 amountOut
    );

    event SwapLiquidityDeposited(address indexed provider, address indexed token, uint256 amount);
    event SwapLiquidityWithdrawn(address indexed recipient, address indexed token, uint256 amount);
    event EmergencyWithdraw(address indexed token, address indexed to, uint256 amount);
    event TargetChainStatusUpdated(uint256 indexed chainId, bool allowed);
    event MaxOperationAmountUpdated(uint256 newMaxAmount);

    constructor(address initialOwner, uint256 _maxOperationAmount) Ownable(initialOwner) {
        maxOperationAmount = _maxOperationAmount;
    }

    modifier withinOperationLimit(uint256 amount) {
        if (maxOperationAmount > 0) {
            require(amount <= maxOperationAmount, "Valor acima do limite por operacao");
        }
        _;
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    function setTargetChainAllowed(uint256 chainId, bool allowed) external onlyOwner {
        require(chainId > 0, "Chain ID invalido");
        allowedTargetChains[chainId] = allowed;
        emit TargetChainStatusUpdated(chainId, allowed);
    }

    function setMaxOperationAmount(uint256 newMaxAmount) external onlyOwner {
        maxOperationAmount = newMaxAmount;
        emit MaxOperationAmountUpdated(newMaxAmount);
    }

    /**
     * @dev Abastece liquidez dedicada ao pool de swap.
     */
    function depositSwapLiquidity(address token, uint256 amount)
        external
        whenNotPaused
        nonReentrant
    {
        require(token != address(0), "Token invalido");
        require(amount > 0, "Quantidade deve ser maior que zero");

        IERC20 erc20 = IERC20(token);
        uint256 balanceBefore = erc20.balanceOf(address(this));

        erc20.safeTransferFrom(msg.sender, address(this), amount);

        uint256 received = erc20.balanceOf(address(this)) - balanceBefore;
        require(received > 0, "Nenhum token recebido");

        swapLiquidity[token] += received;
        emit SwapLiquidityDeposited(msg.sender, token, received);
    }

    /**
     * @dev Retira liquidez dedicada ao swap (sem tocar na liquidez bloqueada de bridge).
     */
    function withdrawSwapLiquidity(address token, uint256 amount)
        external
        onlyOwner
        nonReentrant
    {
        require(token != address(0), "Token invalido");
        require(amount > 0, "Quantidade deve ser maior que zero");
        require(swapLiquidity[token] >= amount, "Liquidez de swap insuficiente");

        swapLiquidity[token] -= amount;
        IERC20(token).safeTransfer(owner(), amount);

        emit SwapLiquidityWithdrawn(owner(), token, amount);
    }

    /**
     * @dev Bloqueia tokens na rede atual para posterior liberacao na rede de destino.
     */
    function bridgeTokens(address token, uint256 amount, uint256 targetChainId)
        external
        whenNotPaused
        nonReentrant
        withinOperationLimit(amount)
    {
        require(token != address(0), "Token invalido");
        require(amount > 0, "A quantidade deve ser maior que zero");
        require(allowedTargetChains[targetChainId], "Rede de destino nao habilitada");

        IERC20 erc20 = IERC20(token);
        uint256 balanceBefore = erc20.balanceOf(address(this));

        erc20.safeTransferFrom(msg.sender, address(this), amount);

        uint256 received = erc20.balanceOf(address(this)) - balanceBefore;
        require(received > 0, "Nenhum token recebido na bridge");

        lockedLiquidity[token] += received;

        emit TokensBridged(msg.sender, token, received, targetChainId, block.timestamp);
    }

    /**
     * @dev Executa troca usando liquidez dedicada do contrato e aplicando taxa de 0.20%.
     */
    function swapTokens(address tokenIn, address tokenOut, uint256 amountIn, uint256 minAmountOut)
        external
        whenNotPaused
        nonReentrant
        withinOperationLimit(amountIn)
    {
        require(tokenIn != address(0) && tokenOut != address(0), "Token invalido");
        require(tokenIn != tokenOut, "Tokens de entrada e saida devem ser diferentes");
        require(amountIn > 0, "Quantidade de entrada invalida");

        IERC20 inToken = IERC20(tokenIn);
        uint256 inBalanceBefore = inToken.balanceOf(address(this));
        inToken.safeTransferFrom(msg.sender, address(this), amountIn);
        uint256 actualIn = inToken.balanceOf(address(this)) - inBalanceBefore;
        require(actualIn > 0, "Nenhum token de entrada recebido");

        uint256 amountOut = (actualIn * (BPS_DENOMINATOR - SWAP_FEE_BPS)) / BPS_DENOMINATOR;
        require(amountOut > 0, "Saida insuficiente apos taxa");
        require(amountOut >= minAmountOut, "Slippage excedido");
        require(swapLiquidity[tokenOut] >= amountOut, "Liquidez insuficiente para swap");

        swapLiquidity[tokenIn] += actualIn;
        swapLiquidity[tokenOut] -= amountOut;

        IERC20(tokenOut).safeTransfer(msg.sender, amountOut);

        emit TokensSwapped(msg.sender, tokenIn, tokenOut, actualIn, amountOut);
    }

    /**
     * @dev Resgate emergencial de tokens presos no contrato quando pausado.
     */
    function emergencyWithdraw(address token, address to, uint256 amount)
        external
        onlyOwner
        whenPaused
        nonReentrant
    {
        require(token != address(0) && to != address(0), "Endereco invalido");
        require(amount > 0, "Quantidade deve ser maior que zero");

        IERC20(token).safeTransfer(to, amount);
        emit EmergencyWithdraw(token, to, amount);
    }
}