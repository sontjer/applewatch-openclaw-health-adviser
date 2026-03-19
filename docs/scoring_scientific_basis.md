# 睡眠评分科学依据（全量）

本文档用于说明 `sleep_scorer_v21.py` 与 `analyze_latest.py` 的评分依据来源、证据强弱和工程化取舍。

## 1. 评分维度与证据映射

| 评分维度 | 当前实现（简述） | 主要科学依据 |
|---|---|---|
| 时长（Duration） | 7-9h 记为最优区间 | AASM/SRS 成人睡眠时长共识：推荐成年人规律获得 >=7h 睡眠，并给出健康风险背景 |
| 规律性（Regularity） | 入睡/起床规律 + 社会时差 proxy + SRI proxy | 睡眠规律性（SRI/时间不规律）与全因死亡、代谢和心血管风险相关 |
| 时机（Timing） | 以中点偏移衡量时相偏离 | 睡眠时相偏移/社会时差与不良健康结局相关 |
| 恢复（Recovery） | HRV + RHR + 呼吸率相对基线 | HRV 标准文件与运动恢复研究支持将自主神经指标作为恢复信号；本项目已改为“睡眠窗口 HRV 中位数” |
| 效率（Efficiency） | 睡眠效率/WASO/觉醒次数（若有） | 睡眠连续性（WASO/觉醒）是标准睡眠结构指标，和结局相关性在不同人群有异质性 |

## 2. 关键文献（按维度）

### 2.1 睡眠时长（Duration）

1. AASM + SRS 共识声明（2015）  
   Recommended Amount of Sleep for a Healthy Adult  
   https://pubmed.ncbi.nlm.nih.gov/25979105/  
2. 方法学与证据讨论（同一共识项目）  
   https://pubmed.ncbi.nlm.nih.gov/26194576/

工程启示：`7-9h` 作为最优带是合理的工程化近似。

### 2.2 睡眠规律性（Regularity）

1. Sleep Regularity Index（SRI）与死亡风险（UK Biobank）  
   https://pubmed.ncbi.nlm.nih.gov/37738616/  
2. SRI 与心代谢风险验证（MESA）  
   https://pubmed.ncbi.nlm.nih.gov/30242174/  
3. 睡眠规律性系统综述（2025）  
   https://pubmed.ncbi.nlm.nih.gov/41259946/

工程启示：规律性应高权重（当前实现 35%）有文献支撑。

### 2.3 睡眠时相/社会时差（Timing）

1. Social jetlag 与肥胖（经典研究）  
   https://pubmed.ncbi.nlm.nih.gov/22578422/  
2. Social jetlag 与抑郁症状（系统综述+Meta，2025）  
   https://pubmed.ncbi.nlm.nih.gov/40597088/  
3. 睡眠时相（L5 中点）与死亡风险（UK Biobank）  
   https://pubmed.ncbi.nlm.nih.gov/38066693/

工程启示：将“时机偏离”纳入评分是合理的，但建议持续做人群本地化校准。

### 2.4 恢复信号（HRV/RHR/RR）

1. HRV 标准文件（Task Force，1996）  
   https://pubmed.ncbi.nlm.nih.gov/8598068/  
2. 训练监测中夜间 HRV 指标研究（女性足球）  
   https://pubmed.ncbi.nlm.nih.gov/33981255/  
3. 晨间标准化 HRV 与恢复/压力关联（2025）  
   https://pubmed.ncbi.nlm.nih.gov/40732543/

工程启示：  
- HRV 可用于恢复维度，但必须控制取样窗口与条件。  
- 本项目已采用“睡眠窗口中位数 + 28天窗口基线中位数”，比“最新单点”更稳健。

### 2.5 睡眠连续性（Efficiency/WASO/Awakenings）

1. 睡眠连续性与死亡风险（含 WASO/觉醒次数分析）  
   https://pubmed.ncbi.nlm.nih.gov/38066693/

工程启示：WASO/觉醒应作为质量辅助特征，而非单独决定总分。

## 3. 与当前代码的一致性说明

- `openclaw_agent/analyze_latest.py`：负责评分输入构建（睡眠窗口 HRV 中位数、28天基线等）。
- `sleep_scorer_v21.py`：负责维度打分与加权汇总。
- 当前模型是“工程化健康评分”，不是医疗诊断模型。

## 4. 已知边界

1. 文献多为队列/观察性证据，不能直接推导个体因果结论。  
2. 可穿戴设备数据质量受佩戴行为、固件算法、采样时段影响。  
3. 评分阈值与权重需结合你自己的长期历史数据持续校准。

## 5. 建议的版本治理

建议每次修改 `sleep_scorer_v21.py` 权重或阈值时，同步记录：
- 变更前后定义
- 使用的数据样本窗口
- 影响评估（分数分布变化、告警变化、误报漏报）
- 对应文献或内部实验编号
