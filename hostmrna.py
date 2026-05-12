import os
import time
import pandas as pd
from Bio import Entrez

# 配置参数 (请换成你自己的 NCBI 账号邮箱)
Entrez.email = "a507283274@gmail.com"
OUTPUT_CSV = "real_host_mrna.csv"

# 我们要搜索的科研级关键字（针对新冠的并发症系统）
SEARCH_TERMS = {
    "immune response AND human[ORGN] AND mRNA[Filter]": ("Immune System", "immune response, cytokine"),
    "lung development AND human[ORGN] AND mRNA[Filter]": ("Respiratory System", "lung respiratory, breathing"),
    "heart contraction AND human[ORGN] AND mRNA[Filter]": ("Cardiovascular", "cardio, heart rhythm"),
    "brain development AND human[ORGN] AND mRNA[Filter]": ("Nervous System", "neuro, brain function")
}


def fetch_real_mrna(batch_size=50):
    records = []

    for query, (pathway, bio_process) in SEARCH_TERMS.items():
        print(f"\n🔍 正在搜索: {query}")
        try:
            # 1. 搜索符合条件的序列 ID
            handle = Entrez.esearch(db="nucleotide", term=query, retmax=batch_size)
            record = Entrez.read(handle)
            handle.close()
            id_list = record["IdList"]

            if not id_list:
                continue

            print(f"找到 {len(id_list)} 个 ID，正在下载序列...")

            # 2. 批量下载完整序列
            fetch_handle = Entrez.efetch(db="nucleotide", id=id_list, rettype="fasta", retmode="text")
            fasta_data = fetch_handle.read().split(">")
            fetch_handle.close()

            # 3. 解析 FASTA 并提取基因名
            for item in fasta_data:
                if not item.strip(): continue
                lines = item.split("\n")
                header = lines[0]
                sequence = "".join(lines[1:]).upper().replace('T', 'U')  # 转录为 RNA

                # 长度过滤：只要 500nt ~ 3000nt 之间的适中长度基因
                if 500 < len(sequence) < 3000:
                    # 从 FASTA 头部尝试提取 accession ID 和基因名字
                    acc_id = header.split(" ")[0]
                    gene_name = "Unknown"
                    if "(" in header and ")" in header:
                        gene_name = header.split("(")[-1].split(")")[0]
                    elif " variant" in header:
                        parts = header.split(",")
                        gene_name = parts[0].split(" ")[-2] if len(parts[0].split(" ")) > 1 else "Gene"

                    records.append({
                        "mrna_id": acc_id,
                        "gene_name": gene_name[:40],  # 防止基因名过长
                        "sequence": sequence,
                        "pathway": pathway,
                        "biological_process": bio_process,
                        "disease_association": "COVID-19 Related"
                    })
            time.sleep(2)  # 遵守 NCBI 频率限制

        except Exception as e:
            print(f"下载出错: {e}")

    # 4. 保存为 CSV，方便后续导入 MySQL
    df = pd.DataFrame(records)
    # 去重
    df = df.drop_duplicates(subset=['mrna_id'])
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✅ 成功下载并提取了 {len(df)} 条真实的宿主靶基因，已保存至 {OUTPUT_CSV}")


if __name__ == "__main__":
    fetch_real_mrna(batch_size=500)  # 你可以把 50 改成 500 以获取海量数据