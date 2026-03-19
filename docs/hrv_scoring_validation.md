# HRV 评分口径科学依据（睡眠窗口优先）

## 结论（用于本项目）

本项目将 HRV 取数口径从“当天最新单点”调整为“睡眠窗口内 HRV 中位数（median）”，并将 baseline 同步调整为“近 28 天每晚睡眠窗口 HRV 中位数的中位数”。

这样做的目标是降低训练后短时波动、体位变化、昼夜节律和随机噪声对恢复评分的干扰，提高日级评分稳定性与可解释性。

## 为什么不用“最新单点”或“全天简单均值”

1. 最新单点：对取样时刻极其敏感，容易被晚间训练后短时自主神经反应放大，导致恢复分不稳定。
2. 全天简单均值：混入了白天活动、体位与行为差异，不利于反映“恢复”这一相对静息状态。
3. 睡眠窗口统计值（尤其中位数）更稳健：
   - 时间条件更一致（可比性更高）
   - 中位数对异常值更不敏感

## 参考证据

1. Task Force（ESC/NASPE）HRV 经典标准文件（1996）：强调 HRV 测量与解释需标准化场景与方法。
   - Circulation. 1996;93(5):1043-1065
   - PubMed: https://pubmed.ncbi.nlm.nih.gov/8598068/

2. 夜间短时 HRV 片段相比整夜平均 HRV 在睡眠相关结局中具有更高判别能力（2025）。
   - Sleep Medicine. 2025
   - PubMed: https://pubmed.ncbi.nlm.nih.gov/39670869/

3. 训练负荷场景中，夜间 HR/HRV 指标具备较好可靠性，适合作为恢复监测信号（2022）。
   - Journal of Strength and Conditioning Research. 2022
   - PubMed: https://pubmed.ncbi.nlm.nih.gov/35894977/

4. 标准化晨间短时 HRV（5 分钟）与主观恢复/疲劳和压力指标存在有意义关联（2025）。
   - Journal of Sports Sciences. 2025
   - PubMed: https://pubmed.ncbi.nlm.nih.gov/40732543/

5. 全时段 HRV 受昼夜节律影响明显，若用于压力识别需去趋势与时段控制（2025）。
   - IEEE Journal of Biomedical and Health Informatics. 2025
   - PubMed: https://pubmed.ncbi.nlm.nih.gov/40297780/

## 实施说明（当前仓库）

- 代码位置：`openclaw_agent/analyze_latest.py`
- 主要策略：
  - `hrv`：取当晚 `bedtime -> wake_time` 窗口内 HRV 中位数
  - `baseline_hrv`：取近 28 天睡眠窗口 HRV 中位数序列的中位数
  - 若当晚窗口无 HRV 样本，则回退到历史兼容口径

## 注意

本口径仍属于“消费级可穿戴 + 工程化评分”的实用方案，不等同临床诊断。建议结合长期趋势、睡眠主观感受和训练负荷共同解读。
