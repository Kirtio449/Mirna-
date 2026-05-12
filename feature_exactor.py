import os
import re
import json
import pandas as pd
import torch as tr  # 用于GPU张量计算
from Bio import SeqIO, Entrez
import ViennaRNA
from joblib import Parallel, delayed
import multiprocessing

# 配置参数
WINDOW_SIZE = 600
STEP_SIZE = 100
MIN_BASE_PAIRS = 16
MIN_SEQ_LENGTH = 60
UNIFY_SEQ_LENGTH = 160  # 仅用于长序列截断，短序列仅保留，不强制统一到该长度
MIRBASE_FILE = "../预测/hairpin.fa"
COV_GENOME_FILE = "covid_genome.fasta"
TRAIN_FEATURES_CSV = "train_features.csv"
COVID_FEATURES_CSV = "covid_features.csv"
HUMAN_NEGATIVE_DIR = "human_genome_sequences"
HUMAN_NEGATIVE_COUNT = 3985

class RNAFeatureExtractor:
    """GPU加速版RNA特征提取器（结合CPU并行+GPU数值计算）"""

    def __init__(self, email):
        self.email = email
        Entrez.email = email
        self.scaler = None
        self.unify_len = UNIFY_SEQ_LENGTH  # 仅用于长序列截断阈值
        self.sub_window_step = 60  # 子窗口滑动步长
        self.n_jobs = multiprocessing.cpu_count()  # 并行任务的CPU核心数
        self.structure_cache = {}  # 二级结构缓存
        self.device = tr.device('cuda' if tr.cuda.is_available() else 'cpu')
        print(f"初始化特征提取器：CPU核心{self.n_jobs}个，计算设备{self.device}")

    def _unify_sequence_length(self, seq):
        """统一序列长度：
        1. 检查有效碱基长度（过滤填充符和N），不足MIN_SEQ_LENGTH则抛错
        2. 长于UNIFY_SEQ_LENGTH（160nt）：按原逻辑左右截断至160nt
        3. 短于/等于UNIFY_SEQ_LENGTH（160nt）：直接返回原序列，不填充
        """
        # 1. 先检查有效碱基长度
        valid_base = seq.replace('N', '')
        if len(valid_base) < MIN_SEQ_LENGTH:
            raise ValueError(f"有效碱基过短（{len(valid_base)}bp < {MIN_SEQ_LENGTH}bp）")

        seq_len = len(seq)
        # 2. 长序列处理：截断至160nt（保留原左右对称截断逻辑）
        if seq_len > self.unify_len:
            trunc_total = seq_len - self.unify_len
            l_trunc, r_trunc = trunc_total // 2, trunc_total - trunc_total // 2
            return seq[l_trunc: seq_len - r_trunc]
        # 3. 短序列/等长序列处理：直接返回原序列，不填充
        else:
            return seq

    def fetch_covid_genome(self, genome_id="NC_045512.2"):
        """获取新冠基因组"""
        try:
            handle = Entrez.efetch(db="nucleotide", id=genome_id, rettype="fasta", retmode="text")
            record = SeqIO.read(handle, "fasta")
            SeqIO.write(record, COV_GENOME_FILE, "fasta")
            return str(record.seq).upper().replace('T', 'U')
        except Exception as e:
            print(f"基因组下载失败，使用本地文件: {e}")
            if os.path.exists(COV_GENOME_FILE):
                record = SeqIO.read(COV_GENOME_FILE, "fasta")
                return str(record.seq).upper().replace('T', 'U')
            else:
                raise Exception("未找到本地基因组文件")

    def fetch_viral_pre_mirnas(self):
        """筛选病毒pre-miRNA"""
        viral_records = []
        viral_prefixes = ['vg', 'hv', 'bv', 'cv', 'sco', 'sar']
        for record in SeqIO.parse(MIRBASE_FILE, "fasta"):
            if any(prefix in record.id[:3] for prefix in viral_prefixes):
                seq = str(record.seq).upper().replace('T', 'U')
                try:
                    unified_seq = self._unify_sequence_length(seq)
                    viral_records.append({
                        'sequence': unified_seq,
                        'id': record.id,
                        'is_viral_mirna': True,
                        'source': 'miRBase_viral'
                    })
                except ValueError as e:
                    print(f"跳过正类样本{record.id}：{e}")
                    continue
        df = pd.DataFrame(viral_records)
        print(f"正类样本数：{len(df)}（长于160nt的已截断，短于160nt的保留原长）")
        return df

    def genome_cutting(self, genome):
        """切割新冠基因组"""
        fragmentlist = []
        genome_len = len(genome)
        print(f"切割新冠基因组：窗口{WINDOW_SIZE}nt，步长{STEP_SIZE}nt...")
        for big_start in range(0, genome_len - WINDOW_SIZE + 1, STEP_SIZE):
            big_end = big_start + WINDOW_SIZE
            big_fragment = genome[big_start: big_end]
            big_fragment_id = f"big_{big_start + 1}-{big_end}"
            # 子片段固定截取160nt，若big_fragment不足160nt则不生成
            for sub_offset in range(0, len(big_fragment) - self.unify_len + 1, self.sub_window_step):
                sub_fragment = big_fragment[sub_offset: sub_offset + self.unify_len]
                if len(sub_fragment) == self.unify_len:
                    fragmentlist.append({
                        'sequence': sub_fragment,
                        'id': f"{big_fragment_id}_sub_{sub_offset + 1}-{sub_offset + self.unify_len}",
                        'parent_big_window': big_fragment_id,
                        'genome_big_start': big_start + 1,
                        'genome_big_end': big_end,
                        'sub_start_in_big': sub_offset + 1,
                        'sub_end_in_big': sub_offset + self.unify_len,
                        'source': 'covid_genome'
                    })
        df = pd.DataFrame(fragmentlist)
        print(f"新冠子片段数：{len(df)}（固定160nt）")
        return df

    def _predict_structure(self, sequence):
        """二级结构预测"""
        seq_hash = hash(sequence)
        if seq_hash in self.structure_cache:
            return self.structure_cache[seq_hash]
        fc = ViennaRNA.fold_compound(sequence)
        ss, mfe = fc.mfe()
        length = len(sequence)
        pair_table = ViennaRNA.ptable(ss)
        base_pairs = sum(1 for i in range(length) if pair_table[i] > i)
        stem_loop_regions = re.findall(r'\([^()]+\)', ss)
        max_stem_length = max([len(r) for r in stem_loop_regions]) if stem_loop_regions else 0
        loop_regions = re.findall(r'\)[^()]*\(', ss) + re.findall(r'^\([^()]*\)', ss)
        total_loop_size = sum([len(r) - 2 for r in loop_regions]) if loop_regions else 0
        result = {
            'structure': ss, 'mfe': mfe, 'nmfe': -mfe / length if length > 0 else 0,
            'base_pairs': base_pairs, 'stem_loop_count': len(stem_loop_regions),
            'max_stem_length': max_stem_length,
            'has_valid_stem_loop': base_pairs >= MIN_BASE_PAIRS and max_stem_length > 0,
            'total_loop_size': total_loop_size
        }
        self.structure_cache[seq_hash] = result
        return result

    def extract_features(self, sequences_df):
        """提取特征"""
        # 1. CPU并行预测二级结构（ViennaRNA只能CPU）
        sequences = sequences_df['sequence'].tolist()
        struct_infos = Parallel(n_jobs=self.n_jobs, verbose=10)(
            delayed(self._predict_structure)(seq) for seq in sequences
        )
        struct_df = pd.DataFrame(struct_infos)

        # 2. 转换数据到GPU张量，加速数值计算
        df = sequences_df.copy()
        df = pd.concat([df, struct_df], axis=1)

        # 碱基计数（先在CPU用Pandas提取，再转GPU）
        seq_series = df['sequence']
        a_count = tr.tensor(seq_series.str.count('A').values, device=self.device)
        u_count = tr.tensor(seq_series.str.count('U').values, device=self.device)
        g_count = tr.tensor(seq_series.str.count('G').values, device=self.device)
        c_count = tr.tensor(seq_series.str.count('C').values, device=self.device)
        n_count = tr.tensor(seq_series.str.count('N').values, device=self.device)

        # 截取后的序列长度
        length = tr.tensor([len(seq) for seq in sequences], device=self.device)

        # 有效碱基长度（GPU计算）
        valid_base_len = (a_count + u_count + g_count + c_count).float()
        valid_base_len = tr.clamp(valid_base_len, min=1)  # 避免除0

        # 比例特征（GPU计算，基于实际长度）
        gc_content = (g_count + c_count).float() / valid_base_len
        au_content = (a_count + u_count).float() / valid_base_len

        # 3. 结构特征转GPU张量（加速后续归一化）
        base_pairs = tr.tensor(df['base_pairs'].values, device=self.device, dtype=tr.float32)
        stem_loop_count = tr.tensor(df['stem_loop_count'].values, device=self.device, dtype=tr.float32)
        max_stem_length = tr.tensor(df['max_stem_length'].values, device=self.device, dtype=tr.float32)
        has_valid_stem_loop = tr.tensor(df['has_valid_stem_loop'].astype(int).values, device=self.device,
                                        dtype=tr.float32)
        total_loop_size = tr.tensor(df['total_loop_size'].values, device=self.device, dtype=tr.float32)
        mfe = tr.tensor(df['mfe'].values, device=self.device, dtype=tr.float32)
        nmfe = tr.tensor(df['nmfe'].values, device=self.device, dtype=tr.float32)

        # 4. 结果转回CPU，整合为DataFrame
        df['a_count'] = a_count.cpu().numpy()
        df['u_count'] = u_count.cpu().numpy()
        df['g_count'] = g_count.cpu().numpy()
        df['c_count'] = c_count.cpu().numpy()
        df['n_count'] = n_count.cpu().numpy()
        df['length'] = length.cpu().numpy()  # 存储实际长度
        df['valid_base_len'] = valid_base_len.cpu().numpy()
        df['gc_content'] = gc_content.cpu().numpy()
        df['au_content'] = au_content.cpu().numpy()
        df['base_pairs'] = base_pairs.cpu().numpy()
        df['stem_loop_count'] = stem_loop_count.cpu().numpy()
        df['max_stem_length'] = max_stem_length.cpu().numpy()
        df['has_valid_stem_loop'] = has_valid_stem_loop.cpu().numpy()
        df['total_loop_size'] = total_loop_size.cpu().numpy()
        df['mfe'] = mfe.cpu().numpy()
        df['nmfe'] = nmfe.cpu().numpy()

        # 筛选特征列
        base_cols = ['id', 'sequence', 'structure', 'length','valid_base_len',
                     'n_count','a_count', 'u_count', 'g_count', 'c_count',
                     'gc_content', 'au_content', 'base_pairs', 'stem_loop_count',
                     'max_stem_length', 'has_valid_stem_loop', 'total_loop_size',
                     'mfe', 'nmfe', 'source']
        if 'parent_big_window' in df.columns:
            base_cols.extend(['parent_big_window', 'genome_big_start',
                              'genome_big_end', 'sub_start_in_big', 'sub_end_in_big'])
        if 'is_viral_mirna' in df.columns:
            base_cols.append('is_viral_mirna')

        return df[base_cols].fillna(0)

    def fetch_human_negative_sequences(self, refresh_data=False):
        """读取负类样本"""
        negative_records = []
        failed_files = []
        if not os.path.exists(HUMAN_NEGATIVE_DIR):
            raise FileNotFoundError(f"负类文件夹不存在：{HUMAN_NEGATIVE_DIR}")
        fasta_files = [f for f in os.listdir(HUMAN_NEGATIVE_DIR) if f.endswith(('.fasta', '.fa'))]
        print(f"发现{len(fasta_files)}个负类FASTA文件...")
        for filename in fasta_files:
            if len(negative_records) >= HUMAN_NEGATIVE_COUNT:
                print(f"已收集{len(negative_records)}个负类样本（达上限）")
                break
            file_path = os.path.join(HUMAN_NEGATIVE_DIR, filename)
            seq_id = os.path.splitext(filename)[0]
            try:
                record = SeqIO.read(file_path, "fasta")
                seq = str(record.seq).upper().replace('T', 'U')
                # 调用修改后的长度统一方法
                unified_seq = self._unify_sequence_length(seq)
                negative_records.append({
                    'sequence': unified_seq, 'id': seq_id,
                    'is_viral_mirna': False, 'source': 'human_cds'
                })
            except Exception as e:
                failed_files.append(f"{filename}: {e}")
                continue
        print(f"负类样本：成功{len(negative_records)}个，失败{len(failed_files)}个")
        if failed_files:
            with open("failed_negative_files.txt", "w") as f:
                f.write("\n".join(failed_files))
        return pd.DataFrame(negative_records)

    def prepare_train_features(self, refresh_data=False):
        """生成训练集特征（无修改，适配动态长度序列的归一化）"""
        if not os.path.exists(TRAIN_FEATURES_CSV) or refresh_data:
            positive_df = self.fetch_viral_pre_mirnas()
            negative_df = self.fetch_human_negative_sequences(refresh_data=refresh_data)
            train_df = pd.concat([positive_df, negative_df], ignore_index=True)
            train_features = self.extract_features(train_df)

            # GPU加速归一化（用PyTorch替代sklearn，适配动态长度）
            numeric_cols = ['length', 'a_count', 'u_count', 'g_count', 'c_count',
                            'gc_content', 'au_content', 'base_pairs', 'stem_loop_count',
                            'max_stem_length', 'has_valid_stem_loop', 'total_loop_size',
                            'mfe', 'nmfe']
            # 转换为GPU张量
            feat_tensor = tr.tensor(train_features[numeric_cols].values, device=self.device, dtype=tr.float32)
            # 计算均值和标准差
            mean = feat_tensor.mean(dim=0)
            std = feat_tensor.std(dim=0) + 1e-8  # 避免除0
            # 归一化
            feat_normalized = (feat_tensor - mean) / std
            # 转回DataFrame
            train_features[numeric_cols] = feat_normalized.cpu().numpy()

            # 保存结果和归一化参数
            train_features.to_csv(TRAIN_FEATURES_CSV, index=False)
            with open('scaler_params.json', 'w') as f:
                json.dump({
                    'mean': mean.cpu().numpy().tolist(),
                    'scale': std.cpu().numpy().tolist(),
                    'cols': numeric_cols
                }, f)
            print(f"训练特征已保存至{TRAIN_FEATURES_CSV}，样本数：{len(train_features)}")
            return train_features
        else:
            print(f"加载训练特征：{TRAIN_FEATURES_CSV}")
            return pd.read_csv(TRAIN_FEATURES_CSV)

    def prepare_covid_features(self, refresh_data=False):
        """生成新冠特征（无修改，适配动态长度序列的归一化）"""
        if not os.path.exists(COVID_FEATURES_CSV) or refresh_data:
            covid_genome = self.fetch_covid_genome()
            covid_df = self.genome_cutting(covid_genome)
            covid_features = self.extract_features(covid_df)

            # 用训练集参数GPU归一化
            with open('scaler_params.json', 'r') as f:
                scaler_data = json.load(f)
            numeric_cols = scaler_data['cols']
            mean = tr.tensor(scaler_data['mean'], device=self.device, dtype=tr.float32)
            std = tr.tensor(scaler_data['scale'], device=self.device, dtype=tr.float32) + 1e-8

            # 转换为GPU张量并归一化
            feat_tensor = tr.tensor(covid_features[numeric_cols].values, device=self.device, dtype=tr.float32)
            feat_normalized = (feat_tensor - mean) / std
            covid_features[numeric_cols] = feat_normalized.cpu().numpy()

            covid_features.to_csv(COVID_FEATURES_CSV, index=False)
            print(f"新冠特征已保存至{COVID_FEATURES_CSV}，片段数：{len(covid_features)}")
            return covid_features
        else:
            print(f"加载新冠特征：{COVID_FEATURES_CSV}")
            return pd.read_csv(COVID_FEATURES_CSV)


if __name__ == "__main__":
    my_email = "17643403299@163.com"  # 替换为你的邮箱
    extractor = RNAFeatureExtractor(email=my_email)
    extractor.prepare_train_features(refresh_data=False)  # 生成训练集
    extractor.prepare_covid_features(refresh_data=False)  # 生成新冠特征