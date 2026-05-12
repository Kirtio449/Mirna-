def predict_target_genes(sequence):
    """预测靶基因（简化版）"""
    # 在实际应用中，这里会调用完整的预测算法
    # 以下是模拟数据生成
    
    # 生成预测结果
    predictions = []
    for i in range(20):
        predictions.append({
            'position': i * 50 + np.random.randint(1, 50),
            'sequence': sequence[i*10:i*10+15] if len(sequence) > i*10+15 else sequence[i*10:],
            'mirna': f"miR-{np.random.randint(1, 500)}",
            'confidence': np.random.choice(['高', '中', '低'], p=[0.2, 0.5, 0.3]),
            'free_energy': round(np.random.uniform(-20, -5), 2),
            'regulated_genes': [f"Gene-{chr(65+j)}" for j in range(np.random.randint(1, 4))]
        })
    
    return {
        'sequence': sequence,
        'predictions': predictions,
        'message': '靶基因预测完成'
    }
