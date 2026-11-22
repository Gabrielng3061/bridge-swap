// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title BridgeSwap
 * @dev Contrato inteligente genérico e modular para gerir operações de Bridge e Swap em redes EVM.
 */
interface IERC20 {
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract BridgeSwap {
    address public owner;

    // Mapeamento para registar liquidez bloqueada por token
    mapping(address => uint256) public lockedLiquidity;

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

    modifier onlyOwner() {
        require(msg.sender == owner, "Apenas o proprietario pode executar esta acao");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    /**
     * @dev Bloqueia tokens na rede atual para posterior liberacao na rede de destino.
     */
    function bridgeTokens(address token, uint256 amount, uint256 targetChainId) external {
        require(amount > 0, "A quantidade deve ser maior que zero");

        IERC20 tokenContract = IERC20(token);

        bool success = tokenContract.transferFrom(msg.sender, address(this), amount);
        require(success, "Falha na transferencia dos tokens para a bridge");

        lockedLiquidity[token] += amount;

        emit TokensBridged(msg.sender, token, amount, targetChainId, block.timestamp);
    }

    /**
     * @dev Executa a troca de um token por outro disponivel no pool do contrato.
     */
    function swapTokens(address tokenIn, address tokenOut, uint256 amountIn, uint256 minAmountOut) external {
        require(amountIn > 0, "Quantidade de entrada invalida");

        IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn);

        uint256 amountOut = minAmountOut;

        require(IERC20(tokenOut).balanceOf(address(this)) >= amountOut, "Liquidez insuficiente para swap");
        IERC20(tokenOut).transfer(msg.sender, amountOut);

        emit TokensSwapped(msg.sender, tokenIn, tokenOut, amountIn, amountOut);
    }

    /**
     * @dev Permite ao owner retirar fundos de emergencia ou ajustar liquidez.
     */
    function emergencyWithdraw(address token, uint256 amount) external onlyOwner {
        IERC20(token).transfer(owner, amount);
    }
}