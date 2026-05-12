import numpy as np
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
from collections import defaultdict
import os
import base64
from io import BytesIO

def predict_regulatory_network(sequence):
    """预测调控网络（简化版）"""
    # 在实际应用中，这里会调用完整的预测算法
    # 以下是模拟数据生成
    
    # miRNA分布
    mirna_distribution = {
        'high': np.random.randint(5, 15),
        'medium': np.random.randint(10, 25),
        'low': np.random.randint(15, 30),
        'total': 0
    }
    mirna_distribution['total'] = sum(mirna_distribution.values())
    
    # miRNA预测结果
    mirna_predictions = []
    for i in range(20):
        mirna_predictions.append({
            'position': i * 50 + np.random.randint(1, 50),
            'sequence': sequence[i*10:i*10+15] if len(sequence) > i*10+15 else sequence[i*10:],
            'mirna': f"miR-{np.random.randint(1, 500)}",
            'confidence': np.random.choice(['高', '中', '低'], p=[0.2, 0.5, 0.3]),
            'free_energy': round(np.random.uniform(-20, -5), 2),
            'regulated_genes': [f"Gene-{chr(65+j)}" for j in range(np.random.randint(1, 4))]
        })
    
    # 调控关系
    regulatory_relationships = []
    for i in range(15):
        regulatory_relationships.append({
            'mirna': f"miR-{np.random.randint(1, 500)}",
            'target_gene': f"Gene-{chr(65+i)}",
            'regulation_type': np.random.choice(['抑制', '促进']),
            'pathway': np.random.choice(['免疫反应', '细胞凋亡', '炎症通路', '病毒复制']),
            'confidence': np.random.choice(['高', '中', '低'], p=[0.3, 0.5, 0.2])
        })
    
    # 症状关联
    symptom_associations = []
    systems = ['呼吸系统', '心血管系统', '神经系统', '消化系统', '免疫系统']
    symptoms_list = {
        '呼吸系统': ['呼吸困难', '咳嗽', '胸痛', '肺纤维化'],
        '心血管系统': ['心肌炎', '心律失常', '血压异常', '血栓形成'],
        '神经系统': ['头痛', '嗅觉丧失', '疲劳', '认知障碍'],
        '消化系统': ['腹泻', '恶心', '食欲不振', '腹痛'],
        '免疫系统': ['细胞因子风暴', '免疫抑制', '自身免疫反应', '淋巴细胞减少']
    }
    
    for i in range(10):
        system = np.random.choice(systems)
        symptoms = np.random.choice(symptoms_list[system], size=np.random.randint(2, 4), replace=False)
        symptom_associations.append({
            'mirna': f"miR-{np.random.randint(1, 500)}",
            'symptoms': list(symptoms),
            'related_genes': [f"Gene-{chr(65+j)}" for j in range(np.random.randint(1, 4))],
            'evidence_strength': np.random.choice(['强', '中等', '弱'], p=[0.2, 0.5, 0.3])
        })
    
    # 症状卡片数据
    symptoms = []
    for system in systems[:3]:
        symptoms.append({
            'system': system,
            'symptoms': np.random.choice(symptoms_list[system], size=3, replace=False).tolist(),
            'icon': ['fas fa-lungs', 'fas fa-heart', 'fas fa-brain', 'fas fa-stomach', 'fas fa-shield-virus'][systems.index(system)]
        })
    
    # 生成网络图
    fig, ax = plt.subplots(figsize=(10, 8))
    
    # 在实际应用中，这里会使用networkx生成网络图
    # 以下是简化的示例
    ax.text(0.5, 0.5, "调控网络可视化\n（实际应用中会显示完整网络图）", 
            ha='center', va='center', fontsize=16)
    ax.axis('off')
    
    # 保存为Base64
    img_buffer = BytesIO()
    plt.savefig(img_buffer, format='png', bbox_inches='tight')
    plt.close(fig)
    img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
    
    # 生成饼图
    fig, ax = plt.subplots(figsize=(6, 6))
    labels = ['高置信度', '中置信度', '低置信度']
    sizes = [mirna_distribution['high'], mirna_distribution['medium'], mirna_distribution['low']]
    colors = ['#4da6ff', '#8cb3d9', '#ff6b6b']
    ax.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    ax.axis('equal')
    
    img_buffer_pie = BytesIO()
    plt.savefig(img_buffer_pie, format='png', bbox_inches='tight')
    plt.close(fig)
    pie_base64 = base64.b64encode(img_buffer_pie.getvalue()).decode('utf-8')
    
    return {
        'sequence': sequence,
        'mirna_distribution': mirna_distribution,
        'regulatory_relationships': regulatory_relationships,
        'symptom_associations': symptom_associations,
        'mirna_predictions': mirna_predictions,
        'symptoms': symptoms,
        'network_image': f"data:image/png;base64,{img_base64}",
        'chart_image': f"data:image/png;base64,{pie_base64}"
    }
