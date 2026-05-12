import os
import re
import traceback
import uuid
import json
import base64
import hashlib
import datetime
import math
import time
from functools import wraps


import mysql.connector
from mysql.connector import pooling
from flask import Flask, request, jsonify, send_file, send_from_directory, redirect
from flask_cors import CORS
from pyvis.network import Network
from werkzeug.utils import secure_filename
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import networkx as nx
from matplotlib.lines import Line2D
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
import torch

app = Flask(__name__)
CORS(app)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ================= 数据库与基础配置 =================
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "507283274",
    "database": "covid_mirna_db",
    "pool_name": "covid_pool",
    "pool_size": 5
}

try:
    db_pool = pooling.MySQLConnectionPool(**db_config)
except Exception as e:
    print(f"数据库连接失败: {e}")
    db_pool = None

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'fasta', 'fa', 'txt'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

JWT_SECRET = 'covid_mirna_secret_key_2023'
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION = 36000


# ================= 辅助函数 =================
def get_db_connection():
    if db_pool: return db_pool.get_connection()
    raise Exception("数据库连接池未初始化")


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def verify_password(stored_password, provided_password):
    return stored_password == hashlib.sha256(provided_password.encode('utf-8')).hexdigest()


def generate_reset_code():
    return str(uuid.uuid4().int)[:6]


def validate_email(email):
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None


def validate_password(password):
    return len(password) >= 8


def create_jwt_token(user_id):
    return jwt.encode({'user_id': user_id, 'exp': time.time() + JWT_EXPIRATION}, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except:
        return None


def jwt_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None

        # 1. 首先尝试从请求头 (Headers) 获取（普通的 API 请求用这个）
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]

        # 2. 🚀修复点：如果请求头里没有，尝试从 URL 参数获取（文件导出下载专用）
        if not token and 'token' in request.args:
            token = request.args.get('token')

        # 3. 验证令牌
        if not token:
            return jsonify({'success': False, 'message': '缺少认证令牌'}), 401

        payload = verify_jwt_token(token)
        if not payload:
            return jsonify({'success': False, 'message': '无效或过期的令牌'}), 401

        request.user_id = payload['user_id']
        return f(*args, **kwargs)

    return decorated_function


# ================= 卷积神经网络预测器类 =================
class PreMirnaPredictor:
    """前体预测器"""

    def __init__(self, model_path='models/best_model.pth', device='cpu'):
        self.device = torch.device(device if torch.cuda.is_available() else 'cpu')
        self.seq_len = 160
        self.model = None

        try:
            from model import mirDNN
            self.model = mirDNN(device=self.device, seq_len=self.seq_len)

            if os.path.exists(model_path):
                checkpoint = torch.load(model_path, map_location=self.device)
                state_dict = checkpoint['model_state_dict'] if 'model_state_dict' in checkpoint else checkpoint
                self.model.load_state_dict(state_dict, strict=False)
                self.model.eval()
                print(f"预训练模型已加载: {model_path}")
            else:
                print(f"未找到 {model_path}，请先运行 generate_weights.py")
        except Exception as e:
            print(f"模型初始化错误: {e}")

    def preprocess_sequence(self, sequence):
        vocab = {'A': 0, 'C': 1, 'G': 2, 'T': 3, 'U': 3}
        windows, positions = [], []
        stride = 50

        for i in range(0, len(sequence) - self.seq_len + 1, stride):
            sub_seq = sequence[i:i + self.seq_len].upper()
            if set(sub_seq).issubset({'A', 'C', 'G', 'T', 'U'}):
                encoded = [vocab.get(base, 14) for base in sub_seq]
                windows.append(encoded)
                positions.append((i, i + self.seq_len))
        if not windows: return None, None
        return torch.LongTensor(windows).to(self.device), positions

    def predict(self, full_virus_sequence):
        if self.model is None: return []
        inputs, positions = self.preprocess_sequence(full_virus_sequence)
        if inputs is None: return []

        predictions = []
        with torch.no_grad():
            try:
                outputs = self.model(inputs)
                probs = torch.softmax(outputs, dim=1)
                positive_probs = probs[:, 1].cpu().numpy()

                threshold = 0.62
                for i, prob in enumerate(positive_probs):
                    if prob > threshold:
                        start, end = positions[i]
                        predictions.append({
                            "mirna_id": f"pred_{start}_{end}",
                            "sequence": full_virus_sequence[start:end],
                            "score": float(prob),
                            "start": start, "end": end,
                            "type": "AI_Predicted"
                        })
            except Exception as e:
                print(f"前向传播错误: {e}")
        return predictions


ai_predictor = PreMirnaPredictor()


# ================= 核心分析类 =================
class VirusHostMiRNAInteraction:
    def __init__(self, virus_sequence=None, analysis_id=None):
        self.virus_sequence = virus_sequence
        self.analysis_id = analysis_id
        self.full_graph = nx.Graph()

        self.human_mirna_virus_interactions = None
        self.virus_mirna_host_interactions = None
        self.affected_pathways = {}
        self.symptom_associations = []
        self.mirna_distribution = {'high': 0, 'medium': 0, 'low': 0, 'total': 0}
        self.regulatory_relationships = []
        self.mirna_predictions = []
        self.symptoms = []
        self.virus_genes = []

        self.human_mirna_data = self._load_data_from_db("human_mirna", limit=200)
        self.virus_mirna_data = self._load_data_from_db("virus_mirna", limit=200)
        self.host_mrna_data = self._load_data_from_db("host_mrna", limit=500)

    def _load_data_from_db(self, table_name, limit=1000):
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
            result = cursor.fetchall()
            return pd.DataFrame(result) if result else pd.DataFrame()
        except:
            return pd.DataFrame()
        finally:
            if 'conn' in locals() and conn: conn.close()

    def save_prediction_result(self, result_type, data):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO prediction_results (analysis_id, result_type, result_data) VALUES (%s, %s, %s)",
                (self.analysis_id, result_type, json.dumps(data))
            )
            conn.commit()
            return True
        except:
            return False
        finally:
            if 'cursor' in locals() and cursor: cursor.close()
            if 'conn' in locals() and conn: conn.close()

    def load_prediction_result(self, result_type):
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT result_data FROM prediction_results WHERE analysis_id = %s AND result_type = %s",
                           (self.analysis_id, result_type))
            result = cursor.fetchone()
            return json.loads(result['result_data']) if result else None
        except:
            return None
        finally:
            if 'conn' in locals() and conn: conn.close()

    def _extract_virus_genes(self):
        if not self.virus_sequence: return []
        sequence = self.virus_sequence.upper().replace('T', 'U')
        genes = []
        for i in range(0, len(sequence) - 1000 + 1, 500):
            genes.append({'gene_id': f"VG_{i + 1}_{i + 1000}", 'sequence': sequence[i:i + 1000], 'function': "病毒蛋白",
                          'start': i + 1, 'end': i + 1000})
        self.virus_genes = genes
        if genes: self.save_prediction_result('gene', genes)
        return genes

    def run_ai_prediction(self):
        if not self.virus_sequence: return False
        print("正在执行前体预测")

        self.predicted_virus_mirnas = ai_predictor.predict(self.virus_sequence)
        if self.predicted_virus_mirnas:
            df_data, valid_predictions = [], []
            for item in self.predicted_virus_mirnas:
                original_pre_seq = item['sequence']
                mature_seq = original_pre_seq
                mirna_id = item['mirna_id']

                try:
                    from miRNA_prediction import predict as extract_mature
                    mature_info = extract_mature(original_pre_seq)
                    if mature_info:
                        guide = mature_info['guide_strand']
                        mature_seq = mature_info[f'mature_{guide}']
                        mirna_id = f"{mirna_id}_{guide}"
                except:
                    pass

                df_data.append({"mirna_id": mirna_id, "sequence": mature_seq, "virus_name": "SARS-CoV-2",
                                "function_description": "AI Predicted"})
                valid_predictions.append(item)

            predicted_df = pd.DataFrame(df_data)
            if not self.virus_mirna_data.empty:
                self.virus_mirna_data = pd.concat([self.virus_mirna_data, predicted_df], ignore_index=True)
            else:
                self.virus_mirna_data = predicted_df
            return True
        return False

    def build_complete_network(self):
        if not self.virus_genes: self._extract_virus_genes()
        self.full_graph.add_nodes_from([g['gene_id'] for g in self.virus_genes], node_type="virus_gene")
        if not self.human_mirna_data.empty: self.full_graph.add_nodes_from(self.human_mirna_data["mirna_id"],
                                                                           node_type="human_mirna")
        if not self.virus_mirna_data.empty: self.full_graph.add_nodes_from(self.virus_mirna_data["mirna_id"],
                                                                           node_type="virus_mirna")
        if not self.host_mrna_data.empty: self.full_graph.add_nodes_from(self.host_mrna_data["mrna_id"],
                                                                         node_type="host_mrna")
        return True, "网络基础构建成功"

    def _calculate_complementarity(self, mirna_seq, target_seq):
        len_m, len_t = len(mirna_seq), len(target_seq)
        if len_m < 8 or len_t < len_m: return 0.0

        seed = mirna_seq[1:8]
        trans = str.maketrans('ACGU', 'UGCA')
        seed_rc = seed.translate(trans)[::-1]

        if (seed_rc[0:5] not in target_seq) and (seed_rc[1:6] not in target_seq) and (seed_rc[2:7] not in target_seq):
            return 0.0

        best_score = 0.0
        m_bases = list(mirna_seq[::-1])

        for i in range(len_t - len_m + 1):
            sub_target = target_seq[i: i + len_m]
            seed_score = 0.0

            for j in range(len_m - 8, len_m - 1):
                mb, tb = m_bases[j], sub_target[j]
                if (mb == 'A' and tb == 'U') or (mb == 'U' and tb == 'A') or (mb == 'C' and tb == 'G') or (
                        mb == 'G' and tb == 'C'):
                    seed_score += 1.0
                elif (mb == 'G' and tb == 'U') or (mb == 'U' and tb == 'G'):
                    seed_score += 0.5

            if seed_score < 5.5: continue

            current_score = seed_score
            for j in range(len_m - 8):
                mb, tb = m_bases[j], sub_target[j]
                if (mb == 'A' and tb == 'U') or (mb == 'U' and tb == 'A') or (mb == 'C' and tb == 'G') or (
                        mb == 'G' and tb == 'C'):
                    current_score += 1.0
                elif (mb == 'G' and tb == 'U') or (mb == 'U' and tb == 'G'):
                    current_score += 0.5

            mb, tb = m_bases[len_m - 1], sub_target[len_m - 1]
            if (mb == 'A' and tb == 'U') or (mb == 'U' and tb == 'A') or (mb == 'C' and tb == 'G') or (
                    mb == 'G' and tb == 'C'):
                current_score += 1.0
            elif (mb == 'G' and tb == 'U') or (mb == 'U' and tb == 'G'):
                current_score += 0.5

            norm = current_score / len_m
            if norm > best_score: best_score = norm
        return best_score

    def predict_human_mirna_virus_interaction(self):
        """预测人体miRNA对病毒的mRNA机制"""
        print("人体miRNA-病毒mRNA分析")
        interactions = []
        if self.human_mirna_data.empty or not self.virus_genes: return False, "缺少数据"

        human_mirnas = self.human_mirna_data.to_dict('records')
        virus_genes_list = self.virus_genes

        for m in human_mirnas: m['clean_seq'] = m['sequence'].upper().replace('T', 'U')
        for g in virus_genes_list: g['clean_seq'] = g['sequence'].upper().replace('T', 'U')

        for mirna in human_mirnas:
            for gene in virus_genes_list:
                score = self._calculate_complementarity(mirna['clean_seq'], gene['clean_seq'])

                # 修复逻辑：进门线降到 0.45，高、中、低标准梯队拉开
                if score > 0.45:
                    confidence = "高" if score > 0.60 else ("中" if score > 0.52 else "低")
                    interactions.append({
                        "mirna_id": mirna["mirna_id"], "virus_gene": gene['gene_id'],
                        "virus_function": gene['function'], "complementarity": score,
                        "confidence": confidence,
                        "free_energy": -score * 20
                    })

                    if score > 0.60:
                        self.mirna_distribution['high'] += 1
                    elif score > 0.52:
                        self.mirna_distribution['medium'] += 1
                    else:
                        self.mirna_distribution['low'] += 1

                    self.mirna_distribution['total'] += 1

        self.human_mirna_virus_interactions = pd.DataFrame(interactions)
        if not self.human_mirna_virus_interactions.empty:
            for _, row in self.human_mirna_virus_interactions.iterrows():
                self.full_graph.add_edge(row["mirna_id"], row["virus_gene"], interaction_type="human_mirna_virus",
                                         score=row["complementarity"])
            self.save_prediction_result('human_mirna_virus',
                                        self.human_mirna_virus_interactions.to_dict(orient='records'))
            return True, self.human_mirna_virus_interactions.to_dict(orient='records')
        return False, "未找到显著互作"

    def predict_virus_mirna_host_interaction(self):
        """预测病毒miRNA靶向宿主mRNA"""
        print("病毒miRNA-人体mRNA分析...")
        interactions = []
        if self.virus_mirna_data.empty or self.host_mrna_data.empty: return False, "缺少数据"

        virus_mirnas = self.virus_mirna_data.to_dict('records')
        host_mrnas = self.host_mrna_data.to_dict('records')

        for v in virus_mirnas: v['clean_seq'] = v['sequence'].upper().replace('T', 'U')
        for h in host_mrnas: h['clean_seq'] = h['sequence'].upper().replace('T', 'U')

        for virus_mirna in virus_mirnas:
            for host_mrna in host_mrnas:
                score = self._calculate_complementarity(virus_mirna['clean_seq'], host_mrna['clean_seq'])

                # 🚀 修复逻辑：保持梯队与上面完全一致
                if score > 0.45:
                    confidence = "高" if score > 0.60 else ("中" if score > 0.52 else "低")
                    self.regulatory_relationships.append({
                        "mirna": virus_mirna["mirna_id"], "target_gene": host_mrna["mrna_id"],
                        "regulation_type": "抑制", "pathway": host_mrna.get("pathway", ""),
                        "confidence": confidence
                    })
                    interactions.append({
                        "virus_mirna_id": virus_mirna["mirna_id"], "host_mrna_id": host_mrna["mrna_id"],
                        "host_gene": host_mrna.get("gene_name", ""), "complementarity": score,
                        "pathway": host_mrna.get("pathway", ""),
                        "biological_process": host_mrna.get("biological_process", "")
                    })

        self.virus_mirna_host_interactions = pd.DataFrame(interactions)
        if not self.virus_mirna_host_interactions.empty:
            for _, row in self.virus_mirna_host_interactions.iterrows():
                self.full_graph.add_edge(row["virus_mirna_id"], row["host_mrna_id"],
                                         interaction_type="virus_mirna_host", score=row["complementarity"])
            self.save_prediction_result('virus_mirna_host',
                                        self.virus_mirna_host_interactions.to_dict(orient='records'))
            if self.regulatory_relationships: self.save_prediction_result('regulatory', self.regulatory_relationships)
        return True, self.virus_mirna_host_interactions.to_dict(orient='records')

    def _hypergeometric_test(self, k, M, n, N):
        p_value = 0.0
        for i in range(k, min(n, N) + 1):
            try:
                prob = (math.comb(n, i) * math.comb(M - n, N - i)) / math.comb(M, N)
                p_value += prob
            except:
                pass
        return p_value

    def analyze_symptoms_enrichment(self):
        """超几何分布检验计算临床症状富集"""
        print("正在进行超几何性状分析...")
        if self.virus_mirna_host_interactions is None or self.virus_mirna_host_interactions.empty: return

        background_genes = 20000  # 人类基因组粗估背景
        pathway_bg = self.host_mrna_data[
            'biological_process'].value_counts().to_dict() if not self.host_mrna_data.empty else {}
        targeted_genes = self.virus_mirna_host_interactions['host_mrna_id'].nunique()
        pathway_tg = self.virus_mirna_host_interactions.drop_duplicates('host_mrna_id')[
            'biological_process'].value_counts().to_dict()

        for bp, k in pathway_tg.items():
            n = pathway_bg.get(bp, k * 10)
            p_val = self._hypergeometric_test(k, background_genes, n, targeted_genes)

            if p_val < 0.05:
                bp_str = str(bp).lower()
                system, symptoms = "", []
                if "immune" in bp_str or "cytokine" in bp_str or "免疫" in bp_str:
                    system = "免疫系统";
                    symptoms = ["细胞因子风暴风险", "免疫失调"]
                elif "lung" in bp_str or "respiratory" in bp_str or "呼吸" in bp_str or "肺" in bp_str:
                    system = "呼吸系统";
                    symptoms = ["肺部炎症反应", "呼吸困难"]
                elif "cardio" in bp_str or "heart" in bp_str or "心" in bp_str:
                    system = "心血管系统";
                    symptoms = ["血管内皮损伤", "心肌炎风险"]
                elif "neuro" in bp_str or "brain" in bp_str or "神经" in bp_str:
                    system = "神经系统";
                    symptoms = ["嗅觉丧失", "认知功能受损"]

                if system and not any(s['system'] == system for s in self.symptoms):
                    self.symptoms.append({
                        "system": system, "symptoms": symptoms,
                        "p_value": f"{p_val:.4e}", "evidence": f"统计学显著富集 (P<0.05)",
                        "icon": "fas fa-microscope"
                    })
        self.save_prediction_result('symptom', self.symptoms)

    def visualize_interaction_network(self, filename="interaction_network.html", min_score=0.45):
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        filename = f"interaction_network_{self.analysis_id}.html"

        if len(self.full_graph.nodes) == 0: return False, "网络为空"

        # 1. 严格过滤低分边，限制最大数量
        valid_edges = [(u, v, d) for u, v, d in self.full_graph.edges(data=True) if d.get("score", 0) > min_score]

        if len(valid_edges) > 400:
            print(f"边数（{len(valid_edges)}）过多，仅截取 Top 400 核心调控关系。")
            valid_edges.sort(key=lambda x: x[2].get("score", 0), reverse=True)
            valid_edges = valid_edges[:400]

        valid_nodes = set([u for u, v, d in valid_edges] + [v for u, v, d in valid_edges])
        if not valid_nodes: return False, "没有符合阈值的连接"

        # 提取连通子图
        subgraph = self.full_graph.subgraph(list(valid_nodes))

        # =====================================================================
        # 使用 Python NetworkX 预计算坐标和 PageRank
        # =====================================================================
        print("正在使用后台矩阵运算预分配网络节点坐标与 PageRank 中心性...")
        # 预计算物理布局坐标
        pos = nx.spring_layout(subgraph, k=0.25, iterations=50, seed=42)
        try:
            pagerank_scores = nx.pagerank(subgraph, weight='score')
        except:
            # 容错降级：如果极端情况下矩阵不收敛，退回度数中心性
            pagerank_scores = nx.degree_centrality(subgraph)

        net = Network(height="900px", width="100%", bgcolor="#ffffff", select_menu=True, cdn_resources="remote")
        net.toggle_physics(False)

        color_map = {"human_mirna": "#4CAF50", "virus_gene": "#F44336", "virus_mirna": "#FF9800",
                     "host_mrna": "#2196F3"}

        # 获取当前网络的最大 PageRank 值，用于节点尺寸的归一化映射
        max_pr = max(pagerank_scores.values()) if pagerank_scores else 1

        # 添加节点并注入预计算好的属性
        for node, data in subgraph.nodes(data=True):
            ntype = data.get("node_type", "unknown")
            deg = subgraph.degree(node)
            pr_val = pagerank_scores.get(node, 0)
            normalized_pr_size = 15 + (pr_val / max_pr) * 35 if max_pr > 0 else 15
            size = min(normalized_pr_size, 50)

            shape = "triangle" if "gene" in ntype else "dot"

            # 放大 NetworkX 生成的 0~1 的坐标系以适应 Pyvis 画布
            x_coord = float(pos[node][0] * 1200)
            y_coord = float(pos[node][1] * 1200)
            tooltip_title = f"节点类型: {ntype}\n连接数 (Degree): {deg}\nPageRank 权重: {pr_val:.4e}"

            net.add_node(
                node, label=node, color=color_map.get(ntype, "#999"),
                size=size, shape=shape, title=tooltip_title,
                x=x_coord, y=y_coord
            )

        # 添加边
        for u, v, data in valid_edges:
            itype = data.get("interaction_type", "")
            color = "rgba(139, 195, 74, 0.4)" if itype == "human_mirna_virus" else "rgba(255, 193, 7, 0.4)"
            net.add_edge(u, v, width=data.get('score', 0) * 3, color=color)

        try:
            abs_path = os.path.abspath(filename)
            net.save_graph(abs_path)
            net.save_graph(filename)
            return True, abs_path
        except:
            return False, "保存失败"

    def generate_mirna_distribution_chart(self):
        if self.mirna_distribution['total'] == 0: return False, ""
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.pie([self.mirna_distribution['high'], self.mirna_distribution['medium'], self.mirna_distribution['low']],
               labels=['高置信度', '中置信度', '低置信度'], colors=['#4da6ff', '#8cb3d9', '#ff6b6b'], autopct='%1.1f%%')
        ax.set_title('miRNA分布')
        buf = BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        return True, base64.b64encode(buf.getvalue()).decode('utf-8')

    def generate_report(self):
        report = {
            "mirna_distribution": self.mirna_distribution,
            "mirna_predictions": self.human_mirna_virus_interactions.to_dict(
                'records') if self.human_mirna_virus_interactions is not None else [],
            "regulatory_relationships": self.regulatory_relationships,
            "virus_genes": self.virus_genes,
            "symptoms": self.symptoms
        }
        success, network_img = self.visualize_interaction_network()
        if success: report["network_image"] = f"data:image/png;base64,{network_img}"
        success, chart_img = self.generate_mirna_distribution_chart()
        if success: report["chart_image"] = f"data:image/png;base64,{chart_img}"

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO analysis_results (record_id, result_data, network_image, chart_image, mirna_distribution, symptoms) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE result_data=VALUES(result_data)",
                (self.analysis_id, json.dumps(report), report.get('network_image', ''), report.get('chart_image', ''),
                 json.dumps(self.mirna_distribution), json.dumps(self.symptoms))
            )
            conn.commit()
        except:
            pass
        return report


# ================= 路由区域 =================
@app.route('/')
def index(): return redirect('/analyze')


@app.route('/analyze')
def analyze_page(): return send_file('index2.html')


@app.route('/static/<path:filename>')
def serve_static(filename): return send_from_directory('static', filename)


@app.route('/get_network_html/lib/<path:filename>')
def serve_network_lib(filename): return send_from_directory(os.path.join(BASE_DIR, 'lib'), filename)


@app.route('/get_network_html/<analysis_id>')
def get_network_html(analysis_id):
    f = f"interaction_network_{analysis_id}.html"
    return send_file(f) if os.path.exists(f) else ("未找到", 404)


@app.route('/auth/register', methods=['POST'])
def register():
    data = request.json
    username, email, pwd, c_pwd = data.get('username'), data.get('email'), data.get('password'), data.get(
        'confirmPassword')
    if pwd != c_pwd: return jsonify({'success': False, 'message': '密码不一致'}), 400
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                       (username, email, hash_password(pwd)))
        conn.commit()
        return jsonify({'success': True, 'message': '注册成功'})
    except:
        return jsonify({'success': False, 'message': '注册失败，可能用户名已存在'}), 500


@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username=%s", (data.get('username'),))
        u = cursor.fetchone()
        if not u or not verify_password(u['password'], data.get('password')): return jsonify(
            {'success': False, 'message': '密码错误'}), 401
        return jsonify(
            {'success': True, 'access_token': create_jwt_token(u['id']), 'user': {'username': u['username']}})
    except:
        return jsonify({'success': False, 'message': '登录失败'}), 500


@app.route('/auth/user', methods=['GET'])
@jwt_required
def get_user_info():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, username, email FROM users WHERE id = %s", (request.user_id,))
        return jsonify({'success': True, 'user': cursor.fetchone()})
    except:
        return jsonify({'success': False}), 500


@app.route('/analysis', methods=['POST'])
@jwt_required
def analyze_sequence():
    user_id = request.user_id
    seq = request.form.get('sequence') if request.form.get('inputMethod') == 'manual' else request.files[
        'file'].read().decode('utf-8')
    opt = {'symptomsPrediction': request.form.get('symptomsPrediction') == 'true'}

    a_id = str(uuid.uuid4())
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO analysis_records (id, user_id, sequence_preview, input_method, options) VALUES (%s, %s, %s, %s, %s)",
            (a_id, user_id, seq[:50] + '...', request.form.get('inputMethod'), json.dumps(opt)))
        conn.commit()
    except:
        pass

    analyzer = VirusHostMiRNAInteraction(virus_sequence=seq, analysis_id=a_id)

    analyzer.run_ai_prediction()
    analyzer.build_complete_network()
    analyzer.predict_human_mirna_virus_interaction()
    if opt['symptomsPrediction']:
        analyzer.predict_virus_mirna_host_interaction()
        analyzer.analyze_symptoms_enrichment()

    res = analyzer.generate_report()
    res['sequence_preview'] = seq[:50]
    return jsonify({'success': True, 'data': res, 'analysis_id': a_id})


@app.route('/history', methods=['GET'])
@jwt_required
def get_history():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, sequence_preview, created_at FROM analysis_records WHERE user_id = %s ORDER BY created_at DESC",
            (request.user_id,))
        return jsonify({'success': True, 'records': [{'id': r['id'], 'date': r['created_at'].strftime('%Y-%m-%d %H:%M'),
                                                      'sequencePreview': r['sequence_preview']} for r in
                                                     cursor.fetchall()]})
    except:
        return jsonify({'success': False}), 500


@app.route('/analysis/<analysis_id>', methods=['GET'])
def get_analysis(analysis_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT result_data FROM analysis_results WHERE record_id = %s", (analysis_id,))
        res = cursor.fetchone()
        return jsonify({'success': True, 'data': json.loads(res['result_data'])}) if res else (
        jsonify({'success': False}), 404)
    except:
        return jsonify({'success': False}), 500


@app.route('/export/pdf/<analysis_id>', methods=['GET'])
@jwt_required
def export_pdf(analysis_id):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 750, f"COVID-miRNA Analysis: {analysis_id}")
    p.save()
    buffer.seek(0)
    return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'report_{analysis_id}.pdf')


@app.route('/export/csv/<analysis_id>', methods=['GET'])
@jwt_required
def export_csv(analysis_id):
    buffer = BytesIO()
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        for t, title in [('human_mirna_virus', 'RNAi'), ('virus_mirna_host', 'Targets'), ('symptom', 'Symptoms')]:
            cursor.execute("SELECT result_data FROM prediction_results WHERE analysis_id=%s AND result_type=%s",
                           (analysis_id, t))
            r = cursor.fetchone()
            if r:
                buffer.write(f"{title}\n".encode())
                buffer.write(pd.DataFrame(json.loads(r['result_data'])).to_csv(index=False).encode())
                buffer.write(b"\n")
    except:
        pass
    buffer.seek(0)
    return send_file(buffer, mimetype='text/csv', as_attachment=True, download_name=f'data_{analysis_id}.csv')


@app.route('/export/image/<analysis_id>', methods=['GET'])
@jwt_required
def export_image(analysis_id):
    fig, ax = plt.subplots()
    ax.text(0.5, 0.5, "Network Visualization Export", ha='center')
    buf = BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return send_file(buf, mimetype='image/png', as_attachment=True, download_name=f'net_{analysis_id}.png')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)