// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title BridgeSwap
 * @dev Contrato inteligente modular para operações de Bridge e Swap em redes EVM,
 *      com pausa de emergência, guarda de reentrância e separação de liquidez.
 */
interface IERC20 {
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract BridgeSwap {
    address public owner;
    bool public paused;

    uint256 private _status;
    uint256 private constant _NOT_ENTERED = 1;
    uint256 private constant _ENTERED = 2;

    // Taxa de swap em basis points (20 bps = 0.20%, mantendo 99.8% de saída)
    uint256 public constant SWAP_FEE_BPS = 20;
    uint256 public constant BPS_DENOMINATOR = 10000;

    // Liquidez bloqueada para bridge por token
    mapping(address => uint256) public lockedLiquidity;

    // Liquidez dedicada a swaps por token
    mapping(address => uint256) public swapLiquidity;

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
    event SwapLiquidityWithdrawn(address indexed owner, address indexed token, uint256 amount);
    event PausedStateChanged(bool paused, address indexed triggeredBy);
    event EmergencyWithdraw(address indexed token, address indexed to, uint256 amount);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    modifier onlyOwner() {
        require(msg.sender == owner, "Apenas o proprietario pode executar esta acao");
        _;
    }

    modifier whenNotPaused() {
        require(!paused, "Contrato pausado em modo de emergencia");
        _;
    }

    modifier nonReentrant() {
        require(_status != _ENTERED, "Chamada reentrante bloqueada");
        _status = _ENTERED;
        _;
        _status = _NOT_ENTERED;
    }

    constructor() {
        owner = msg.sender;
        _status = _NOT_ENTERED;
        paused = false;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Novo owner invalido");
        address prev = owner;
        owner = newOwner;
        emit OwnershipTransferred(prev, newOwner);
    }

    function setPaused(bool _paused) external onlyOwner {
        paused = _paused;
        emit PausedStateChanged(_paused, msg.sender);
    }

    /**
     * @dev Abastece liquidez dedicada ao pool de swap.
     */
    function depositSwapLiquidity(address token, uint256 amount) external nonReentrant {
        require(token != address(0), "Token invalido");
        require(amount > 0, "Quantidade deve ser maior que zero");

        swapLiquidity[token] += amount;

        bool ok = IERC20(token).transferFrom(msg.sender, address(this), amount);
        require(ok, "Falha ao depositar liquidez de swap");

        emit SwapLiquidityDeposited(msg.sender, token, amount);
    }

    /**
     * @dev Retira liquidez dedicada ao swap (sem tocar na liquidez bloqueada de bridge).
     */
    function withdrawSwapLiquidity(address token, uint256 amount) external onlyOwner nonReentrant {
        require(token != address(0), "Token invalido");
        require(amount > 0, "Quantidade deve ser maior que zero");
        require(swapLiquidity[token] >= amount, "Liquidez de swap insuficiente");

        swapLiquidity[token] -= amount;

        bool ok = IERC20(token).transfer(owner, amount);
        require(ok, "Falha ao retirar liquidez de swap");

        emit SwapLiquidityWithdrawn(owner, token, amount);
    }

    /**
     * @dev Bloqueia tokens na rede atual para posterior liberacao na rede de destino.
     */
    function bridgeTokens(address token, uint256 amount, uint256 targetChainId)
        external
        whenNotPaused
        nonReentrant
    {
        require(token != address(0), "Token invalido");
        require(amount > 0, "A quantidade deve ser maior que zero");
        require(targetChainId > 0, "Chain ID de destino invalido");

        lockedLiquidity[token] += amount;

        bool success = IERC20(token).transferFrom(msg.sender, address(this), amount);
        require(success, "Falha na transferencia dos tokens para a bridge");

        emit TokensBridged(msg.sender, token, amount, targetChainId, block.timestamp);
    }

    /**
     * @dev Executa troca usando liquidez dedicada do contrato e aplicando taxa de 0.20%.
     */
    function swapTokens(address tokenIn, address tokenOut, uint256 amountIn, uint256 minAmountOut)
        external
        whenNotPaused
        nonReentrant
    {
        require(tokenIn != address(0) && tokenOut != address(0), "Token invalido");
        require(tokenIn != tokenOut, "Tokens de entrada e saida devem ser diferentes");
        require(amountIn > 0, "Quantidade de entrada invalida");

        uint256 amountOut = (amountIn * (BPS_DENOMINATOR - SWAP_FEE_BPS)) / BPS_DENOMINATOR;
        require(amountOut > 0, "Saida calculada muito pequena");
        require(amountOut >= minAmountOut, "Slippage acima do limite permitido");
        require(swapLiquidity[tokenOut] >= amountOut, "Liquidez de swap insuficiente");

        swapLiquidity[tokenOut] -= amountOut;
        swapLiquidity[tokenIn] += amountIn;

        bool pulled = IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn);
        require(pulled, "Falha ao receber token de entrada");

        bool sent = IERC20(tokenOut).transfer(msg.sender, amountOut);
        require(sent, "Falha ao enviar token de saida");

        emit TokensSwapped(msg.sender, tokenIn, tokenOut, amountIn, amountOut);
    }

    /**
     * @dev Retirada de emergencia restrita ao owner (apenas quando pausado).
     */
    function emergencyWithdraw(address token, uint256 amount) external onlyOwner nonReentrant {
        require(paused, "Pause o contrato antes de executar retirada de emergencia");
        require(token != address(0), "Token invalido");
        require(amount > 0, "Quantidade deve ser maior que zero");

        uint256 contractBalance = IERC20(token).balanceOf(address(this));
        require(contractBalance >= amount, "Saldo do contrato insuficiente");

        if (lockedLiquidity[token] >= amount) {
            lockedLiquidity[token] -= amount;
        } else {
            lockedLiquidity[token] = 0;
        }

        bool ok = IERC20(token).transfer(owner, amount);
        require(ok, "Falha na retirada de emergencia");

        emit EmergencyWithdraw(token, owner, amount);
    }
}