"""
Pre-miRNA Mature Sequence Prediction Pipeline
只输出概率大于阈值且预测成功的行，并附带置信度。

用法:
    python miRNA_prediction.py input.csv output.csv -t 0.8
"""

import math
import sys
import csv
import argparse
import os


def predict_structure(sequence):
    try:
        import RNA
        structure, mfe = RNA.fold(sequence)
        return structure, mfe
    except ImportError:
        return _nussinov_fold(sequence)


def _can_pair(a, b):
    return (a, b) in {
        ('A', 'U'), ('U', 'A'),
        ('G', 'C'), ('C', 'G'),
        ('G', 'U'), ('U', 'G'),
    }


def _nussinov_fold(seq):
    n = len(seq)
    dp = [[0] * n for _ in range(n)]
    for span in range(4, n):
        for i in range(n - span):
            j = i + span
            dp[i][j] = dp[i + 1][j]
            dp[i][j] = max(dp[i][j], dp[i][j - 1])
            if _can_pair(seq[i], seq[j]):
                dp[i][j] = max(dp[i][j], dp[i + 1][j - 1] + 1)
            for k in range(i + 1, j):
                dp[i][j] = max(dp[i][j], dp[i][k] + dp[k + 1][j])
    struct = ['.'] * n

    def traceback(i, j):
        if i >= j:
            return
        if dp[i][j] == dp[i + 1][j]:
            traceback(i + 1, j)
        elif dp[i][j] == dp[i][j - 1]:
            traceback(i, j - 1)
        elif _can_pair(seq[i], seq[j]) and dp[i][j] == dp[i + 1][j - 1] + 1:
            struct[i] = '('
            struct[j] = ')'
            traceback(i + 1, j - 1)
        else:
            for k in range(i + 1, j):
                if dp[i][j] == dp[i][k] + dp[k + 1][j]:
                    traceback(i, k)
                    traceback(k + 1, j)
                    break

    traceback(0, n - 1)
    structure = ''.join(struct)
    approx_mfe = -structure.count('(') * 1.8
    return structure, approx_mfe


def build_pair_map(structure):
    pair_map = {}
    stack = []
    for i, ch in enumerate(structure):
        if ch == '(':
            stack.append(i)
        elif ch == ')':
            j = stack.pop()
            pair_map[j] = i
            pair_map[i] = j
    return pair_map


def identify_regions(structure, pair_map):
    n = len(structure)
    innermost_left = -1
    for i in range(n):
        if structure[i] == '(':
            innermost_left = i
    if innermost_left == -1:
        raise ValueError("未找到碱基配对")
    innermost_right = pair_map[innermost_left]
    return (0, innermost_left, innermost_left + 1,
            innermost_right - 1, innermost_right, n - 1)


def generate_candidates(sequence, structure, pair_map, regions, mature_len=22):
    n = len(sequence)
    arm5_s, arm5_e, loop_s, loop_e, arm3_s, arm3_e = regions
    ideal_5prime = arm5_s + mature_len
    ideal_3prime = arm3_e - mature_len + 1

    ideal_cut_from_3 = None
    for pos in range(max(0, ideal_3prime - 2), min(n, ideal_3prime + 3)):
        if pos in pair_map and pair_map[pos] < loop_s:
            ideal_cut_from_3 = pair_map[pos] + 1
            break
    if ideal_cut_from_3 is None:
        ideal_cut_from_3 = ideal_5prime

    seen = set()
    candidates = []
    for center in (ideal_5prime, ideal_cut_from_3):
        for offset in range(-4, 5):
            cut5 = center + offset
            if cut5 < 18 or cut5 > loop_s or cut5 in seen:
                continue
            seen.add(cut5)
            ref_pos = cut5 - 1
            if ref_pos in pair_map:
                m3_start = pair_map[ref_pos] - 2
            else:
                m3_start = arm3_s
            m3_start = max(m3_start, arm3_s - 2, 0)
            m3_end = min(m3_start + mature_len, n)
            candidates.append({
                'cut5': cut5,
                'offset_from_ideal': cut5 - ideal_5prime,
                'm5_start': arm5_s,
                'm5_end': cut5,
                'm3_start': m3_start,
                'm3_end': m3_end,
            })
    return candidates


_STACK = {
    ('AU','AU'):-0.9,('AU','CG'):-2.2,('AU','GC'):-2.1,('AU','UA'):-1.1,
    ('AU','GU'):-1.4,('AU','UG'):-0.6,
    ('CG','AU'):-2.1,('CG','CG'):-3.3,('CG','GC'):-2.4,('CG','UA'):-2.1,
    ('CG','GU'):-2.1,('CG','UG'):-1.4,
    ('GC','AU'):-2.4,('GC','CG'):-3.4,('GC','GC'):-3.3,('GC','UA'):-2.2,
    ('GC','GU'):-2.5,('GC','UG'):-1.5,
    ('UA','AU'):-1.3,('UA','CG'):-2.4,('UA','GC'):-2.1,('UA','UA'):-0.9,
    ('UA','GU'):-1.0,('UA','UG'):-0.6,
    ('GU','AU'):-1.3,('GU','CG'):-2.5,('GU','GC'):-2.1,('GU','UA'):-1.4,
    ('GU','GU'):-0.5,('GU','UG'):-0.3,
    ('UG','AU'):-1.0,('UG','CG'):-1.5,('UG','GC'):-1.4,('UG','UA'):-0.6,
    ('UG','GU'):-0.3,('UG','UG'):-0.5,
}
_DEFAULT_STACK = -1.5


def _local_stacking_energy(sequence, pair_map, positions, num_pairs=4):
    paired = []
    for p in positions:
        if p in pair_map:
            paired.append((p, pair_map[p]))
        if len(paired) >= num_pairs:
            break
    energy = 0.0
    for k in range(len(paired) - 1):
        i1, j1 = paired[k]
        i2, j2 = paired[k + 1]
        bp1 = sequence[i1] + sequence[j1]
        bp2 = sequence[i2] + sequence[j2]
        energy += _STACK.get((prev_pair := bp1, bp2), _DEFAULT_STACK)
    return energy


def extract_features(sequence, structure, pair_map, cand):
    n = len(sequence)
    m5s, m5e = cand['m5_start'], min(cand['m5_end'], n)
    m3s, m3e = max(cand['m3_start'], 0), min(cand['m3_end'], n)
    seq5 = sequence[m5s:m5e]
    seq3 = sequence[m3s:m3e]
    f = {}
    f['offset'] = abs(cand['offset_from_ideal'])
    f['len_dev'] = abs(len(seq5) - 22) + abs(len(seq3) - 22)
    paired5 = sum(1 for i in range(m5s, m5e) if i in pair_map)
    paired3 = sum(1 for i in range(m3s, m3e) if i in pair_map)
    f['pair_rate_5p'] = paired5 / max(len(seq5), 1)
    f['pair_rate_3p'] = paired3 / max(len(seq3), 1)
    seed_s = m5s + 1
    seed_e = min(m5s + 8, m5e)
    seed_paired = sum(1 for i in range(seed_s, seed_e) if i in pair_map)
    f['seed_pair_rate'] = seed_paired / max(seed_e - seed_s, 1)
    bulge_cnt, max_bulge, cur = 0, 0, 0
    for i in range(m5s, m5e):
        if structure[i] == '.':
            cur += 1
        else:
            if 0 < cur <= 4:
                bulge_cnt += 1
                max_bulge = max(max_bulge, cur)
            cur = 0
    for i in range(m3s, m3e):
        if structure[i] == '.':
            cur += 1
        else:
            if 0 < cur <= 4:
                bulge_cnt += 1
                max_bulge = max(max_bulge, cur)
            cur = 0
    f['bulge_count'] = bulge_cnt
    f['max_bulge'] = max_bulge
    f['first_U_5p'] = 1 if seq5 and seq5[0] == 'U' else 0
    f['first_U_3p'] = 1 if seq3 and seq3[0] == 'U' else 0
    pos5_list = list(range(m5s, m5e))
    pos3_list = list(range(m3e - 1, m3s - 1, -1))
    dG5 = _local_stacking_energy(sequence, pair_map, pos5_list)
    dG3 = _local_stacking_energy(sequence, pair_map, pos3_list)
    f['ddG'] = dG5 - dG3
    total_e = 0.0
    prev_pair = None
    for i in range(m5s, m5e):
        if i in pair_map:
            j = pair_map[i]
            bp = sequence[i] + sequence[j]
            if prev_pair is not None:
                total_e += _STACK.get((prev_pair, bp), _DEFAULT_STACK)
            prev_pair = bp
        else:
            prev_pair = None
    f['total_energy'] = total_e
    return f


def score_candidate(f):
    s_dicer = math.exp(-f['offset'] ** 2 / 8.0)
    s_len = math.exp(-f['len_dev'] ** 2 / 8.0)
    s_struct = (0.25 * f['pair_rate_5p']
                + 0.25 * f['pair_rate_3p']
                + 0.30 * f['seed_pair_rate']
                + 0.08 * f['first_U_5p']
                + 0.04 * f['first_U_3p']
                - 0.06 * f['bulge_count']
                - 0.03 * f['max_bulge'])
    s_thermo = -f['total_energy'] / 50.0
    return 0.35 * s_dicer + 0.10 * s_len + 0.30 * s_struct + 0.25 * s_thermo


def strand_selection(f):
    p5 = 1.0 / (1.0 + math.exp(-f['ddG'] * 2.0))
    p5 += 0.08 * f['first_U_5p'] - 0.08 * f['first_U_3p']
    return max(0.01, min(0.99, p5))


def predict(sequence):
    sequence = sequence.upper().replace('T', 'U').strip()
    n = len(sequence)
    try:
        structure, mfe = predict_structure(sequence)
        pair_map = build_pair_map(structure)
        regions = identify_regions(structure, pair_map)
    except Exception:
        return None
    candidates = generate_candidates(sequence, structure, pair_map, regions)
    if not candidates:
        return None
    best_sc, best_cand, best_feat = -1e9, None, None
    for c in candidates:
        feat = extract_features(sequence, structure, pair_map, c)
        sc = score_candidate(feat)
        if sc > best_sc:
            best_sc, best_cand, best_feat = sc, c, feat
    p5 = strand_selection(best_feat)
    guide = "5p" if p5 >= 0.5 else "3p"
    guide_conf = max(p5, 1.0 - p5)
    seq5 = sequence[best_cand['m5_start']:min(best_cand['m5_end'], n)]
    seq3 = sequence[max(best_cand['m3_start'], 0):min(best_cand['m3_end'], n)]
    return {
        'mature_5p': seq5,
        'mature_3p': seq3,
        'guide_strand': guide,
        'prediction_score': round(best_sc, 4),
        'guide_confidence': round(guide_conf, 4),
    }


def process_csv(input_path, output_path, threshold,
                seq_col='raw_sequence', prob_col='prediction_probability'):
    if not os.path.isfile(input_path):
        print(f"[ERROR] File not found: {input_path}")
        sys.exit(1)

    with open(input_path, 'r', newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames) if reader.fieldnames else []
        rows = list(reader)

    for col in (seq_col, prob_col):
        if col not in fieldnames:
            print(f"[ERROR] Column '{col}' not found. Available: {fieldnames}")
            sys.exit(1)

    new_cols = ['mature_5p', 'mature_3p', 'guide_strand',
                'prediction_score', 'guide_confidence']
    out_fields = fieldnames + new_cols
    out_rows = []
    ok, skip, err = 0, 0, 0

    for row in rows:
        try:
            prob = float(row[prob_col])
        except (ValueError, TypeError):
            skip += 1
            continue
        if prob <= threshold:
            skip += 1
            continue
        seq = row.get(seq_col, '').strip()
        if not seq:
            skip += 1
            continue
        try:
            result = predict(seq)
        except Exception:
            err += 1
            continue
        if result is None:
            err += 1
            continue
        for c in new_cols:
            row[c] = result[c]
        out_rows.append(row)
        ok += 1

    with open(output_path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=out_fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"[DONE] Predicted: {ok} | Skipped: {skip} | Errors: {err}")
    print(f"[DONE] Saved to : {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Predict mature miRNA from pre-miRNA in CSV.")
    parser.add_argument('input_csv', help="Input CSV path")
    parser.add_argument('output_csv', help="Output CSV path")
    parser.add_argument('-t', '--threshold', type=float, default=0.8,
                        help="Probability threshold (default 0.8)")
    parser.add_argument('--seq-col', default='raw_sequence',
                        help="Sequence column name")
    parser.add_argument('--prob-col', default='prediction_probability',
                        help="Probability column name")
    args = parser.parse_args()
    process_csv(args.input_csv, args.output_csv, args.threshold,
                args.seq_col, args.prob_col)