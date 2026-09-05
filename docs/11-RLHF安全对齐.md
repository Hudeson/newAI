# 第 11 章 · RLHF 安全对齐

> 上游对应章节：RLHF 安全对齐 ·
> [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter11/RLHF.pdf) ·
> [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter11/README.md) ·
> [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter11/RLHF.ipynb)
>
> 本章代码：`dive/rlhf.py` 　实验脚本：`labs/lab11_rlhf.py`

## 本章目标

1. 用 Bradley-Terry 模型把成对偏好训成一个奖励函数；
2. 实现序列级 PPO，理解 **KL 惩罚为什么必须扣在奖励上而不是加在损失里**；
3. 实现 DPO，理解它为什么能绕过奖励模型与采样；
4. 亲手量出**对齐税**：礼貌率、多样性、与参考模型的 KL 这三个数必须一起看。

## 原理

### 为什么需要 RLHF

SFT 教模型「怎么回答」，但「好回答」没有唯一标准答案，只有相对偏好：
同一个问题的两个回答，人类能说出哪个更好，却写不出一个可微的评分函数。
RLHF 的三步走就是为了把这种偏好变成可优化的目标。

### 第一步：奖励模型（Bradley-Terry）

给定偏好对 $(x, y_w \succ y_l)$，假设人类以如下概率做出选择：

$$
p(y_w \succ y_l \mid x) = \sigma\big(r_\phi(x,y_w) - r_\phi(x,y_l)\big)
$$

最大化其对数似然即得损失：

$$
\mathcal{L}_{RM} = -\mathbb{E}\big[\log \sigma\big(r_\phi(x,y_w) - r_\phi(x,y_l)\big)\big]
$$

**关键性质：BT 损失只约束奖励的相对大小，绝对尺度是自由的。**
$r \to r + c$ 不改变损失。这直接导致 PPO 里必须对优势做归一化，
否则学习率的实际含义会随奖励尺度漂移。

### 第二步：PPO

把语言模型当策略 $\pi_\theta$，最大化奖励，同时用 KL 约束别跑太远：

$$
\max_\theta \; \mathbb{E}_{y \sim \pi_\theta}\Big[r_\phi(x,y) - \beta \log\frac{\pi_\theta(y|x)}{\pi_{ref}(y|x)}\Big]
$$

InstructGPT 的做法是把 KL 项**扣进奖励**：

$$
\tilde r = r_\phi(x,y) - \beta\big(\log \pi_\theta(y|x) - \log \pi_{ref}(y|x)\big)
$$

再用裁剪目标更新：

$$
\mathcal{L}_{PPO} = -\mathbb{E}\Big[\min\big(\rho\,A,\; \mathrm{clip}(\rho, 1-\epsilon, 1+\epsilon)\,A\big)\Big],
\quad \rho = \frac{\pi_\theta(y|x)}{\pi_{\theta_{old}}(y|x)}
$$

**这里有一个必踩的坑。** 如果把 KL 当成一项直接加到损失里
（$\mathcal{L} = -\rho A + \beta \log \pi_\theta$），训练一定崩。原因是：
这一项会对**每一条被采样到的序列**都施加一个方向一致的「降低其对数概率」的梯度，
而概率之和恒为 1，于是概率质量被推给那些**没被采样到**的序列 —— 模型越训越乱。
扣进奖励则只改变各条轨迹的**相对**优劣，语义才是正确的「别跑太远」。

这个 bug 在本仓库开发过程中真实发生过一次，实验现象是 PPO 的礼貌率和奖励
双双下降。修正提交见 `dive/rlhf.py::ppo_train` 的注释。

### 第三步：DPO

DPO 的洞察是：上面那个带 KL 约束的最优策略有闭式解

$$
\pi^*(y|x) \propto \pi_{ref}(y|x)\exp\big(r(x,y)/\beta\big)
$$

反解出 $r$ 再代回 BT 损失，奖励模型就被消掉了：

$$
\mathcal{L}_{DPO} = -\log \sigma\Big(\beta\big[\log\tfrac{\pi_\theta(y_w|x)}{\pi_{ref}(y_w|x)} - \log\tfrac{\pi_\theta(y_l|x)}{\pi_{ref}(y_l|x)}\big]\Big)
$$

于是 RLHF 从「训 RM + 采样 + PPO」变成了一个**普通的分类损失**：
不需要奖励模型，不需要在线采样，不需要价值网络。这是 DPO 成为主流的原因。

$\beta$ 在这里就是「允许偏离参考模型多远」的旋钮，它直接标定了对齐税。

## 代码导读

`dive/rlhf.py` 的结构：

```python
@dataclass
class Preference:                 # prompt / chosen / rejected
class SequenceRewardModel:        # 词嵌入 -> 平均池化 -> MLP -> 标量
def bradley_terry_loss(chosen_rewards, rejected_rewards)
def train_reward_model(...)
def sequence_logprob(model, ids, prompt_len) -> Tensor    # 只统计回答部分，保留计算图
def dpo_loss(policy, reference, preference, beta)
def train_dpo(...)
def ppo_train(policy, reward_model, prompts, ..., kl_coef=0.05)
```

`sequence_logprob` 是 DPO 与 PPO 的共同基础，它只对**回答部分**求和：

```python
logits = model(ids[None, :-1])
log_probs = logits.log_softmax(axis=-1)
positions = np.arange(prompt_len - 1, len(targets))     # 从回答的第一个 token 起
picked = log_probs[(np.zeros_like(positions), positions, targets[positions])]
return picked.sum()
```

`tests/test_rlhf.py::test_sequence_logprob_matches_manual_computation` 用手算的
方式把它验证了一遍。

PPO 里 KL 惩罚的位置（本章的重点）：

```python
rewards = np.array(rewards)
penalties = np.array(penalties)          # old_logprob - ref_logprob
shaped = rewards - kl_coef * penalties   # ← 扣在奖励上，不是加在损失里
advantages = shaped - shaped.mean()
if advantages.std() > 1e-8:
    advantages = advantages / advantages.std()
```

裁剪与取最小值都要可微，实现在 `_clip` 与 `_minimum`：区间外梯度为 0，
取最小时梯度只流向被选中的那一侧。

### 评测口径：`labs/lab11_rlhf.py::Bench`

三个指标集中在一个类里，保证所有方法用**完全相同**的口径比较：

| 指标 | 定义 | 为什么必须看 |
| --- | --- | --- |
| 礼貌率 | 采样回答全部由礼貌词构成的比例 | 对齐目标达成度 |
| 多样性 | 240 次采样里不同回答的种数 | 只看礼貌率会得到「只会说一句话」的模型 |
| 与 SFT 的 KL | 回答部分对数似然之差 | 跑偏了多远，reward hacking 的风险代理 |

## 动手实验

```bash
python3 -m labs.lab11_rlhf                        # 约 18 秒
python3 -m labs.lab11_rlhf --ppo-iterations 40    # PPO 训久一点
python3 -m labs.lab11_rlhf --rm-epochs 200        # 奖励模型训久一点
```

任务是一个两句话的客服助手：6 个问题，每个问题各 9 条礼貌回答
（「好的 / 没问题 / 当然」×「马上为您处理 / 这就为您查询 / 很高兴帮忙」）
和 9 条生硬回答（「不知道 / 别问了 / 懒得说」×「自己查去 / 没空 / 问别人」）。

### 实测结果

**实验 A：SFT 基线**

```
SFT 基线          礼貌率 51.7%   多样性 19   与SFT的KL +0.00
```

礼貌率恰好在 50% 附近 —— 模型两种说法都学会了，但不知道该偏向哪种。
采样示例：

```
问:天气 -> 当然很高兴帮忙
问:天气 -> 不知道没空
问:路线 -> 懒得说问别人
```

**实验 B：奖励模型**（54 个偏好对，80 epoch）

```
成对准确率      100.0%
礼貌回答平均分   +3.97
生硬回答平均分   -5.55
分数间隔        +9.52
BT loss        0.6924 -> 0.0001
```

奖励模型从未见过「礼貌」这个词，它只是从成对比较里学出了一个打分函数。

**实验 C：DPO 与对齐税**

| 方法 | 礼貌率 | 多样性 | 与 SFT 的 KL |
| --- | --- | --- | --- |
| SFT 基线 | 51.7% | 19 | +0.00 |
| DPO β=0.5 | 97.9% | **14** | +0.68 |
| DPO β=0.1 | 99.6% | 9 | +1.70 |
| DPO β=0.02 | **100.0%** | **5** | +1.79 |

DPO(β=0.1) 的偏好对数似然间隔达到 **+41.06**（SFT 起点约为 0）。

**实验 D：PPO 与 KL 惩罚**

| 方法 | 礼貌率 | 多样性 | 与 SFT 的 KL | 平均奖励 |
| --- | --- | --- | --- | --- |
| SFT 基线 | 51.7% | 19 | +0.00 | — |
| PPO kl_coef=0.05 | 100.0% | 9 | **+1.21** | -0.37 → +3.57 |
| PPO kl_coef=0.0 | 99.2% | 8 | **+9.11** | -0.37 → +3.96 |

### 读法

**对齐税是可测量的，不是修辞。** 看 DPO 那张表的第 2、3 列：
礼貌率从 97.9% 涨到 100.0%（+2.1 个点），代价是多样性从 14 种塌到 5 种（-64%）。
$\beta$ 越小约束越松，模型越是把所有概率质量堆到少数几句「安全回答」上。
这就是真实系统里「对齐后的模型变得千篇一律」的微观机制。
如果你的评测只报礼貌率，你会认为 β=0.02 是最优配置。

**KL 惩罚不提升指标，它保护指标的可信度。** PPO 两组的礼貌率（100.0% vs 99.2%）
和最终奖励（+3.57 vs +3.96）几乎一样，差别全在 KL 那一列：
带惩罚的稳在 +1.21，去掉惩罚一路漂到 +9.11。**多出来的 8 个 nat 的漂移什么也没换来。**
这就是「白跑的漂移」：策略只对奖励模型负责，而奖励模型只是人类偏好的一个有偏近似；
离参考模型越远，这个近似越不可信，钻空子（reward hacking）的空间越大。

顺带看训练日志里 kl_coef=0.0 的轨迹：第 10 轮 KL 还是 +1.62，第 15 轮突然跳到 +7.46。
没有约束的策略优化不是平滑地漂走，而是在某一刻脱缰。

## 思考题

1. 把 `ppo_train` 里的 `shaped = rewards - kl_coef * penalties` 改成
   在损失里加一项 `+ kl_coef * new_logprob`，跑一遍看礼貌率与奖励怎么变。
   用「概率之和为 1」解释你观察到的现象。
2. DPO 的 β → 0 与 β → ∞ 两个极限分别对应什么？
   为什么 β=0.02 时多样性塌缩，但礼貌率反而满分？
3. 奖励模型的分数间隔是 +9.52，如果不做优势归一化会怎样？
   （提示：把 `advantages / advantages.std()` 那行注掉再跑）
4. 本章的 chosen/rejected 是程序化配对的（第 i 条礼貌 vs 第 i 条生硬）。
   如果偏好标注里有 10% 的噪声（把一对标反），DPO 和 PPO 谁更脆弱？动手试试。
5. 第 6 章的结论是「字符串防御挡不住语义改写」，第 10 章的结论是
   「护栏必须在执行前」。本章的对齐训练能替代它们中的哪一个？为什么不能替代另一个？
6. 「多样性」在本实验里用「不同回答的种数」度量。这个指标有什么问题？
   换成 self-BLEU 或输出分布的熵会怎样？

## 延伸阅读

- Ouyang et al. **Training language models to follow instructions with human feedback (InstructGPT).**
  NeurIPS 2022. [arXiv:2203.02155](https://arxiv.org/abs/2203.02155)
- Rafailov et al. **Direct Preference Optimization: Your Language Model is Secretly a Reward Model.**
  NeurIPS 2023. [arXiv:2305.18290](https://arxiv.org/abs/2305.18290)
- Schulman et al. **Proximal Policy Optimization Algorithms.** 2017.
  [arXiv:1707.06347](https://arxiv.org/abs/1707.06347)
- Christiano et al. **Deep Reinforcement Learning from Human Preferences.** NIPS 2017.
  [arXiv:1706.03741](https://arxiv.org/abs/1706.03741)
- Bai et al. **Constitutional AI: Harmlessness from AI Feedback.** 2022.
  [arXiv:2212.08073](https://arxiv.org/abs/2212.08073)
- Gao et al. **Scaling Laws for Reward Model Overoptimization.** ICML 2023.
  [arXiv:2210.10760](https://arxiv.org/abs/2210.10760)（reward hacking 的定量研究）
- Kirk et al. **Understanding the Effects of RLHF on LLM Generalisation and Diversity.** ICLR 2024.
  [arXiv:2310.06452](https://arxiv.org/abs/2310.06452)（对齐税的实证）
- Bradley & Terry. **Rank Analysis of Incomplete Block Designs.** Biometrika 1952.
- 工程实现：[huggingface/trl](https://github.com/huggingface/trl)、
  [OpenRLHF/OpenRLHF](https://github.com/OpenRLHF/OpenRLHF)

## 回到目录

[README](../README.md) · 上一章：[第 10 章 · 智能体安全](10-智能体安全.md)
