import os
import re
import uuid
import json
import base64
import hashlib
import datetime
import mysql.connector
from mysql.connector import pooling
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import networkx as nx
from matplotlib.lines import Line2D

app = Flask(__name__)
CORS(app)

# 数据库连接池配置
db_config = {
    "host": "localhost",
    "user": "your_db_user",
    "password": "your_db_password",
    "database": "covid_mirna_db",
    "pool_name": "covid_pool",
    "pool_size": 5
}

# 创建数据库连接池
db_pool = pooling.MySQLConnectionPool(**db_config)

# 文件上传配置
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'fasta', 'fa', 'txt'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# JWT密钥
app.config['SECRET_KEY'] = 'your_very_secret_key_here'

def get_db_connection():
    return db_pool.get_connection()

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def verify_password(stored_password, provided_password):
    return stored_password == hashlib.sha256(provided_password.encode('utf-8')).hexdigest()

def generate_reset_code():
    return str(uuid.uuid4().int)[:6]

def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password):
    return len(password) >= 8

@app.route('/auth/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    confirm_password = data.get('confirmPassword')

    if not all([username, email, password, confirm_password]):
        return jsonify({'success': False, 'message': '所有字段都是必填的'}), 400

    if password != confirm_password:
        return jsonify({'success': False, 'message': '两次输入的密码不一致'}), 400

    if not validate_email(email):
        return jsonify({'success': False, 'message': '无效的电子邮件格式'}), 400

    if not validate_password(password):
        return jsonify({'success': False, 'message': '密码长度至少为8个字符'}), 400

    hashed_password = hash_password(password)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 检查用户名或邮箱是否已存在
        cursor.execute("SELECT * FROM users WHERE username = %s OR email = %s", (username, email))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': '用户名或邮箱已被使用'}), 400
        
        # 创建新用户
        cursor.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (username, email, hashed_password)
        )
        conn.commit()
        
        # 获取新创建的用户
        cursor.execute("SELECT id, username, email FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        
        return jsonify({
            'success': True,
            'message': '注册成功',
            'user': {
                'id': user[0],
                'username': user[1],
                'email': user[2]
            }
        })
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码是必填的'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 401
        
        if not verify_password(user['password'], password):
            return jsonify({'success': False, 'message': '密码错误'}), 401
        
        # 生成JWT令牌（简化版，实际应使用JWT库）
        token = str(uuid.uuid4())
        
        return jsonify({
            'success': True,
            'message': '登录成功',
            'access_token': token,
            'user': {
                'id': user['id'],
                'username': user['username'],
                'email': user['email']
            }
        })
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/auth/user', methods=['GET'])
def get_user_info():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'success': False, 'message': '未提供认证令牌'}), 401
    
    # 简化版令牌验证（实际应使用JWT库）
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 在实际应用中，这里应该验证JWT令牌并获取用户ID
        # 为简化，我们假设令牌有效并直接查询用户
        cursor.execute("SELECT id, username, email FROM users LIMIT 1")
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        return jsonify({
            'success': True,
            'user': user
        })
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/analysis', methods=['POST'])
def analyze_sequence():
    # 获取用户ID（实际应从JWT令牌中获取）
    user_id = request.form.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': '未提供用户ID'}), 401
    
    # 获取分析选项
    options = {
        'regulatoryNetwork': request.form.get('regulatoryNetwork') == 'true',
        'symptomsPrediction': request.form.get('symptomsPrediction') == 'true'
    }
    
    # 获取序列数据
    input_method = request.form.get('inputMethod')
    sequence = None
    file_info = None
    
    if input_method == 'manual':
        sequence = request.form.get('sequence')
        if not sequence:
            return jsonify({'success': False, 'message': '未提供RNA序列'}), 400
    else:  # file
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '未上传文件'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': '未选择文件'}), 400
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # 读取文件内容
            with open(file_path, 'r') as f:
                sequence = f.read()
            
            file_info = {
                'name': filename,
                'size': os.path.getsize(file_path),
                'type': 'FASTA' if filename.endswith(('.fasta', '.fa')) else 'TXT'
            }
        else:
            return jsonify({'success': False, 'message': '不支持的文件格式'}), 400
    
    # 生成分析ID
    analysis_id = str(uuid.uuid4())
    
    # 序列预览
    sequence_preview = sequence[:50] + '...' if len(sequence) > 50 else sequence
    
    # 保存分析记录
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO analysis_records (id, user_id, sequence_preview, input_method, file_info, options) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (analysis_id, user_id, sequence_preview, input_method, 
             json.dumps(file_info) if file_info else None, json.dumps(options))
        )
        conn.commit()
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()
    
    # 执行分析（这里使用模拟数据，实际应调用分析算法）
    analysis_data = generate_mock_analysis_data(sequence, options)
    
    # 保存分析结果
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO analysis_results (record_id, result_data) "
            "VALUES (%s, %s)",
            (analysis_id, json.dumps(analysis_data))
        )
        conn.commit()
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()
    
    return jsonify({
        'success': True,
        'data': analysis_data,
        'analysis_id': analysis_id
    })

@app.route('/history', methods=['GET'])
def get_history():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': '未提供用户ID'}), 401
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute(
            "SELECT id, sequence_preview, created_at FROM analysis_records "
            "WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,)
        )
        records = cursor.fetchall()
        
        history = []
        for record in records:
            history.append({
                'id': record['id'],
                'date': record['created_at'].strftime('%Y-%m-%d %H:%M'),
                'sequencePreview': record['sequence_preview']
            })
        
        return jsonify({
            'success': True,
            'records': history
        })
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/analysis/<analysis_id>', methods=['GET'])
def get_analysis(analysis_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute(
            "SELECT result_data FROM analysis_results WHERE record_id = %s",
            (analysis_id,)
        )
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'success': False, 'message': '未找到分析结果'}), 404
        
        return jsonify({
            'success': True,
            'data': json.loads(result['result_data'])
        })
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/auth/forgot-password', methods=['POST'])
def forgot_password():
    email = request.json.get('email')
    if not email:
        return jsonify({'success': False, 'message': '请输入电子邮箱'}), 400
    
    if not validate_email(email):
        return jsonify({'success': False, 'message': '无效的电子邮件格式'}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'message': '该邮箱未注册'}), 404
        
        # 生成重置码
        code = generate_reset_code()
        expires_at = datetime.datetime.now() + datetime.timedelta(minutes=10)
        
        # 保存重置请求
        cursor.execute(
            "INSERT INTO password_resets (user_id, email, code, expires_at) "
            "VALUES (%s, %s, %s, %s)",
            (user['id'], email, code, expires_at)
        )
        conn.commit()
        
        # 在实际应用中，这里应该发送包含验证码的电子邮件
        print(f"Password reset code for {email}: {code}")  # 仅用于开发环境
        
        return jsonify({
            'success': True,
            'message': '验证码已发送到您的邮箱'
        })
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/auth/verify-reset-code', methods=['POST'])
def verify_reset_code():
    email = request.json.get('email')
    code = request.json.get('code')
    
    if not email or not code:
        return jsonify({'success': False, 'message': '请输入电子邮箱和验证码'}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute(
            "SELECT * FROM password_resets "
            "WHERE email = %s AND code = %s AND used = 0 AND expires_at > NOW()",
            (email, code)
        )
        reset_request = cursor.fetchone()
        
        if not reset_request:
            return jsonify({'success': False, 'message': '无效或过期的验证码'}), 400
        
        return jsonify({
            'success': True,
            'message': '验证码有效'
        })
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/auth/reset-password', methods=['POST'])
def reset_password():
    email = request.json.get('email')
    code = request.json.get('code')
    new_password = request.json.get('newPassword')
    confirm_password = request.json.get('confirmPassword')
    
    if not all([email, code, new_password, confirm_password]):
        return jsonify({'success': False, 'message': '所有字段都是必填的'}), 400
    
    if new_password != confirm_password:
        return jsonify({'success': False, 'message': '两次输入的密码不一致'}), 400
    
    if not validate_password(new_password):
        return jsonify({'success': False, 'message': '密码长度至少为8个字符'}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 验证重置请求
        cursor.execute(
            "SELECT * FROM password_resets "
            "WHERE email = %s AND code = %s AND used = 0 AND expires_at > NOW()",
            (email, code)
        )
        reset_request = cursor.fetchone()
        
        if not reset_request:
            return jsonify({'success': False, 'message': '无效或过期的验证码'}), 400
        
        # 更新密码
        hashed_password = hash_password(new_password)
        cursor.execute(
            "UPDATE users SET password = %s WHERE email = %s",
            (hashed_password, email)
        )
        
        # 标记重置请求为已使用
        cursor.execute(
            "UPDATE password_resets SET used = 1 WHERE id = %s",
            (reset_request['id'],)
        )
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': '密码重置成功'
        })
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/export/pdf/<analysis_id>', methods=['GET'])
def export_pdf(analysis_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute(
            "SELECT result_data FROM analysis_results WHERE record_id = %s",
            (analysis_id,)
        )
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'success': False, 'message': '未找到分析结果'}), 404
        
        analysis_data = json.loads(result['result_data'])
        
        # 创建PDF
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        
        # 添加标题
        p.setFont("Helvetica-Bold", 16)
        p.drawString(100, height - 50, "COVID-miRNA分析报告")
        
        # 添加分析ID
        p.setFont("Helvetica", 12)
        p.drawString(100, height - 80, f"分析ID: {analysis_id}")
        p.drawString(100, height - 100, f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        # 添加miRNA分布
        p.setFont("Helvetica-Bold", 14)
        p.drawString(100, height - 140, "miRNA分布")
        p.setFont("Helvetica", 12)
        p.drawString(100, height - 160, f"高置信度: {analysis_data['mirna_distribution']['high']}")
        p.drawString(100, height - 180, f"中置信度: {analysis_data['mirna_distribution']['medium']}")
        p.drawString(100, height - 200, f"低置信度: {analysis_data['mirna_distribution']['low']}")
        p.drawString(100, height - 220, f"总计: {analysis_data['mirna_distribution']['total']}")
        
        # 添加症状分析
        p.setFont("Helvetica-Bold", 14)
        p.drawString(100, height - 260, "症状分析")
        p.setFont("Helvetica", 12)
        y_pos = height - 280
        for symptom in analysis_data['symptoms']:
            p.drawString(120, y_pos, f"{symptom['system']}: {', '.join(symptom['symptoms'])}")
            y_pos -= 20
            if y_pos < 100:
                p.showPage()
                y_pos = height - 50
        
        p.save()
        buffer.seek(0)
        
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'analysis_{analysis_id}.pdf')
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/export/csv/<analysis_id>', methods=['GET'])
def export_csv(analysis_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute(
            "SELECT result_data FROM analysis_results WHERE record_id = %s",
            (analysis_id,)
        )
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'success': False, 'message': '未找到分析结果'}), 404
        
        analysis_data = json.loads(result['result_data'])
        
        # 创建CSV
        buffer = BytesIO()
        
        # miRNA预测结果 - 使用UTF-8编码
        buffer.write("miRNA预测结果\n".encode('utf-8'))
        df_mirna = pd.DataFrame(analysis_data['mirna_predictions'])
        buffer.write(df_mirna.to_csv(index=False).encode('utf-8'))
        buffer.write(b"\n\n")
        
        # 调控关系 - 使用UTF-8编码
        buffer.write("调控关系\n".encode('utf-8'))
        df_regulatory = pd.DataFrame(analysis_data['regulatory_relationships'])
        buffer.write(df_regulatory.to_csv(index=False).encode('utf-8'))
        buffer.write(b"\n\n")
        
        # 症状关联 - 使用UTF-8编码
        buffer.write("症状关联\n".encode('utf-8'))
        df_symptoms = pd.DataFrame(analysis_data['symptom_associations'])
        buffer.write(df_symptoms.to_csv(index=False).encode('utf-8'))
        
        buffer.seek(0)
        
        return send_file(
            buffer, 
            mimetype='text/csv; charset=utf-8',  # 指定字符集
            as_attachment=True, 
            download_name=f'analysis_{analysis_id}.csv'
        )
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/export/image/<analysis_id>', methods=['GET'])
def export_image(analysis_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute(
            "SELECT result_data FROM analysis_results WHERE record_id = %s",
            (analysis_id,)
        )
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'success': False, 'message': '未找到分析结果'}), 404
        
        analysis_data = json.loads(result['result_data'])
        
        # 创建网络图
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # 创建图
        G = nx.Graph()
        
        # 添加节点
        node_types = {
            "human_mirna": "#4CAF50",  # 绿色
            "virus_gene": "#F44336",   # 红色
            "virus_mirna": "#FF9800",  # 橙色
            "host_mrna": "#2196F3"     # 蓝色
        }
        
        # 添加边
        edge_types = {
            "gene_interaction": "#BDBDBD",  # 灰色
            "human_mirna_virus": "#8BC34A", # 浅绿色
            "virus_mirna_host": "#FFC107"   # 黄色
        }
        
        # 布局
        pos = nx.spring_layout(G, seed=42)
        
        # 绘制节点
        for node_type, color in node_types.items():
            nodes = [n for n, t in nx.get_node_attributes(G, "node_type").items() if t == node_type]
            nx.draw_networkx_nodes(G, pos, nodelist=nodes, node_color=color, node_size=300, ax=ax)
        
        # 绘制边
        for edge_type, color in edge_types.items():
            edges = [(u, v) for u, v, d in G.edges(data=True) if d["interaction_type"] == edge_type]
            nx.draw_networkx_edges(G, pos, edgelist=edges, edge_color=color, width=1.5, ax=ax)
        
        # 添加图例
        legend_elements = [
            Line2D([0], [0], marker='o', color='w', label='人体miRNA', 
                   markerfacecolor=node_types["human_mirna"], markersize=10),
            Line2D([0], [0], marker='o', color='w', label='新冠病毒基因', 
                   markerfacecolor=node_types["virus_gene"], markersize=10),
            Line2D([0], [0], marker='o', color='w', label='病毒miRNA', 
                   markerfacecolor=node_types["virus_mirna"], markersize=10),
            Line2D([0], [0], marker='o', color='w', label='人体mRNA', 
                   markerfacecolor=node_types["host_mrna"], markersize=10),
            Line2D([0], [0], color=edge_types["gene_interaction"], label='基因互作'),
            Line2D([0], [0], color=edge_types["human_mirna_virus"], label='人体miRNA-病毒干扰'),
            Line2D([0], [0], color=edge_types["virus_mirna_host"], label='病毒miRNA-人体mRNA干扰')
        ]
        
        ax.legend(handles=legend_elements, loc='best')
        ax.set_title("新冠病毒-人体miRNA/mRNA互作网络")
        plt.axis('off')
        
        # 保存图像到内存
        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buffer.seek(0)
        
        return send_file(buffer, mimetype='image/png', as_attachment=True, download_name=f'network_{analysis_id}.png')
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'数据库错误: {err}'}), 500
    finally:
        cursor.close()
        conn.close()

def generate_mock_analysis_data(sequence, options):
    """生成模拟分析数据（实际应用中应替换为真实分析）"""
    return {
        "mirna_distribution": {
            "high": np.random.randint(5, 15),
            "medium": np.random.randint(10, 20),
            "low": np.random.randint(3, 10),
            "total": np.random.randint(20, 40)
        },
        "regulatory_relationships": [
            {
                "mirna": f"miR-{np.random.randint(100, 500)}",
                "target_gene": f"Gene-{chr(65 + i)}",
                "regulation_type": np.random.choice(["抑制", "促进"]),
                "pathway": np.random.choice(["免疫反应", "细胞凋亡", "炎症通路"]),
                "confidence": np.random.choice(["高", "中", "低"])
            } for i in range(10)
        ],
        "symptom_associations": [
            {
                "mirna": f"miR-{np.random.randint(100, 500)}",
                "symptoms": np.random.choice([
                    ["呼吸困难", "咳嗽"],
                    ["发热", "乏力"],
                    ["嗅觉丧失", "味觉障碍"],
                    ["腹泻", "恶心"]
                ], 1)[0],
                "related_genes": [f"Gene-{chr(65 + i)}" for i in range(np.random.randint(1, 3))],
                "evidence_strength": np.random.choice(["强", "中等", "弱"])
            } for i in range(5)
        ],
        "mirna_predictions": [
            {
                "position": f"{i*100}-{(i+1)*100}",
                "sequence": sequence[i*10:i*10+15] + "..." if len(sequence) > i*10+15 else sequence[i*10:],
                "mirna": f"miR-{np.random.randint(100, 500)}",
                "confidence": np.random.choice(["高", "中", "低"]),
                "free_energy": round(np.random.uniform(-20, -5), 2),
                "regulated_genes": [f"VG_{i}_{i+100}"]
            } for i in range(5)
        ],
        "symptoms": [
            {
                "system": "呼吸系统",
                "symptoms": ["呼吸困难", "咳嗽", "肺纤维化"],
                "icon": "fas fa-lungs"
            },
            {
                "system": "免疫系统",
                "symptoms": ["细胞因子风暴", "免疫抑制", "淋巴细胞减少"],
                "icon": "fas fa-shield-virus"
            },
            {
                "system": "神经系统",
                "symptoms": ["头痛", "嗅觉丧失", "疲劳", "认知障碍"],
                "icon": "fas fa-brain"
            },
            {
                "system": "心血管系统",
                "symptoms": ["心肌炎", "心律失常", "血栓形成"],
                "icon": "fas fa-heart"
            }
        ]
    }

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
