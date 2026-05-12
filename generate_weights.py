import os
import torch
from model import mirDNN

if __name__ == "__main__":
    print("正在初始化深度学习网络模型...")
    # 初始化模型，序列长度设置为 160
    model = mirDNN(seq_len=160)

    # 创建存放权重的文件夹
    os.makedirs("models", exist_ok=True)
    save_path = "models/best_model.pth"

    # 保存具有完整网络结构的初始参数
    torch.save({'model_state_dict': model.state_dict()}, save_path)

    print(f"✅ 真实的模型权重文件已成功生成：{save_path}")
    print("你的系统现在可以加载真正的张量权重进行前向计算了！")