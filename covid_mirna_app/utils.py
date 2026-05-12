import os
import csv
import io
import matplotlib.pyplot as plt
from fpdf import FPDF
import base64

def generate_pdf_report(result):
    """生成PDF报告"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    # 添加标题
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="COVID-miRNA分析报告", ln=True, align='C')
    pdf.ln(10)
    
    # 添加基本信息
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
    pdf.cell(200, 10, txt=f"序列长度: {len(result.get('sequence', ''))} bp", ln=True)
    pdf.ln(10)
    
    # 添加miRNA分布
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt="miRNA分布", ln=True)
    pdf.set_font("Arial", size=12)
    
    mirna_dist = result.get('mirna_distribution', {})
    pdf.cell(200, 10, txt=f"高置信度: {mirna_dist.get('high', 0)}", ln=True)
    pdf.cell(200, 10, txt=f"中置信度: {mirna_dist.get('medium', 0)}", ln=True)
    pdf.cell(200, 10, txt=f"低置信度: {mirna_dist.get('low', 0)}", ln=True)
    pdf.cell(200, 10, txt=f"总计: {mirna_dist.get('total', 0)}", ln=True)
    pdf.ln(10)
    
    # 添加症状分析
    symptoms = result.get('symptoms', [])
    if symptoms:
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(200, 10, txt="可能出现的症状", ln=True)
        pdf.set_font("Arial", size=12)
        
        for symptom in symptoms:
            pdf.cell(200, 10, txt=f"- {symptom['system']}: {', '.join(symptom['symptoms'])}", ln=True)
        pdf.ln(10)
    
    # 添加图表
    if 'chart_image' in result:
        img_data = base64.b64decode(result['chart_image'].split(',')[1])
        img_path = "temp_chart.png"
        with open(img_path, 'wb') as f:
            f.write(img_data)
        
        pdf.image(img_path, x=10, y=pdf.get_y(), w=180)
        os.remove(img_path)
        pdf.ln(85)
    
    # 添加详细结果
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt="详细分析结果", ln=True)
    pdf.set_font("Arial", size=10)
    
    # miRNA预测结果表
    predictions = result.get('mirna_predictions', [])
    if predictions:
        pdf.cell(200, 10, txt="miRNA预测结果:", ln=True)
        col_widths = [20, 40, 30, 20, 20, 30]
        headers = ["位置", "序列", "miRNA", "置信度", "自由能", "调控基因"]
        
        # 表头
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 10, txt=header, border=1)
        pdf.ln()
        
        # 数据行
        for pred in predictions[:10]:  # 只显示前10条
            pdf.cell(col_widths[0], 10, txt=str(pred.get('position', '')), border=1)
            pdf.cell(col_widths[1], 10, txt=pred.get('sequence', '')[:15] + '...', border=1)
            pdf.cell(col_widths[2], 10, txt=pred.get('mirna', ''), border=1)
            pdf.cell(col_widths[3], 10, txt=pred.get('confidence', ''), border=1)
            pdf.cell(col_widths[4], 10, txt=str(pred.get('free_energy', '')), border=1)
            pdf.cell(col_widths[5], 10, txt=', '.join(pred.get('regulated_genes', [])[:2]) + '...', border=1)
            pdf.ln()
    
    return pdf.output(dest='S').encode('latin1')

def generate_csv_data(result):
    """生成CSV数据"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # 写入基本信息
    writer.writerow(['分析报告', 'COVID-miRNA分析平台'])
    writer.writerow(['分析时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow(['序列长度', len(result.get('sequence', ''))])
    writer.writerow([])
    
    # miRNA分布
    mirna_dist = result.get('mirna_distribution', {})
    writer.writerow(['miRNA分布'])
    writer.writerow(['高置信度', mirna_dist.get('high', 0)])
    writer.writerow(['中置信度', mirna_dist.get('medium', 0)])
    writer.writerow(['低置信度', mirna_dist.get('low', 0)])
    writer.writerow(['总计', mirna_dist.get('total', 0)])
    writer.writerow([])
    
    # 调控关系
    relationships = result.get('regulatory_relationships', [])
    if relationships:
        writer.writerow(['miRNA-基因调控关系'])
        writer.writerow(['miRNA', '靶基因', '调控类型', '通路', '置信度'])
        for rel in relationships:
            writer.writerow([
                rel.get('mirna', ''),
                rel.get('target_gene', ''),
                rel.get('regulation_type', ''),
                rel.get('pathway', ''),
                rel.get('confidence', '')
            ])
        writer.writerow([])
    
    # 症状关联
    associations = result.get('symptom_associations', [])
    if associations:
        writer.writerow(['miRNA-症状关联分析'])
        writer.writerow(['miRNA', '相关症状', '关联基因', '证据强度'])
        for assoc in associations:
            writer.writerow([
                assoc.get('mirna', ''),
                '; '.join(assoc.get('symptoms', [])),
                '; '.join(assoc.get('related_genes', [])),
                assoc.get('evidence_strength', '')
            ])
    
    return output.getvalue().encode('utf-8')

def generate_chart_image(result):
    """生成图表图片"""
    mirna_dist = result.get('mirna_distribution', {})
    labels = ['高置信度', '中置信度', '低置信度']
    sizes = [mirna_dist.get('high', 0), mirna_dist.get('medium', 0), mirna_dist.get('low', 0)]
    colors = ['#4da6ff', '#8cb3d9', '#ff6b6b']
    
    plt.figure(figsize=(8, 6))
    plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    plt.axis('equal')
    plt.title('miRNA分布')
    
    # 保存到字节流
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png')
    img_buffer.seek(0)
    
    return img_buffer.getvalue()
