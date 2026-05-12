import torch
import torch.nn as nn
from resnet import ResNet


class mirDNN(nn.Module):
    """
    完整的 miRNA 预测深度神经网络模型
    包含嵌入层(Embedding) -> 维度适配器 -> 残差网络(ResNet) -> 全连接分类器
    """

    def __init__(self, device='cpu', seq_len=160, width=64, n_resnets=3, kernel_size=3):
        super(mirDNN, self).__init__()
        self.seq_len = seq_len
        self.device = torch.device(device)

        # 1. 嵌入层：将碱基索引映射为 15 维的密集向量
        # num_embeddings 设为 50 是为了包含 pad token (45) 等特殊字符
        self.embedding = nn.Embedding(num_embeddings=50, embedding_dim=15, padding_idx=45)

        # ---------------------------------------------------------
        # 【核心修复点】：1x1 卷积维度适配器 (Projection Layer)
        # 作用：将 15 通道的输入平滑地“升维”到 64 通道 (width)
        # 这样进入 ResNet 时，输入和输出都是 64 维，相加就不会报错了！
        # ---------------------------------------------------------
        self.input_proj = nn.Conv1d(in_channels=15, out_channels=width, kernel_size=1)

        # 2. ResNet 特征提取层
        # 注意：这里的 in_dim 已经变成了 width (64)
        self.resnet = ResNet(in_dim=width, nfilters=[width] * n_resnets, ksizes=[kernel_size] * n_resnets)

        # 3. 分类器
        self.classifier = nn.Sequential(
            nn.AdaptiveAvgPool1d(1),  # 全局平均池化，把任意序列长度压缩成 1 个特征点
            nn.Flatten(),
            nn.Linear(width, 2)  # 最终输出 2 个节点：[非miRNA得分, 是miRNA得分]
        )
        self.to(self.device)

    def forward(self, x, mfe=None):
        """
        前向传播函数
        :param x: 序列的 Tensor, 形状 [batch_size, seq_len]
        :param mfe: 最小自由能(可选), 形状 [batch_size, 1]
        """
        # --- 阶段 1：序列编码 ---
        x = self.embedding(x)  # 形状变为: [batch_size, seq_len, 15]
        x = x.permute(0, 2, 1)  # 形状变为: [batch_size, 15, seq_len] (因为1D卷积要求通道数在中间)

        # --- 阶段 2：维度拉升适配 ---
        x = self.input_proj(x)  # 形状变为: [batch_size, 64, seq_len]

        # --- 阶段 3：深层特征提取 ---
        x = self.resnet(x)  # 形状变为: [batch_size, 64, seq_len]

        # --- 阶段 4：分类输出 ---
        out = self.classifier(x)  # 形状变为: [batch_size, 2]

        return out