# 动手学大模型 · 纯 NumPy 实现

> **一份可在普通 CPU 上跑通的大模型教学仓库：11 章、11 个实验、每个结论都有可复现的实测数字。**
>
> 运行时依赖只有 NumPy。不需要 GPU，不需要联网，不下载任何权重。

---

## 项目定位

本仓库是上海交通大学开源课程 **《动手学大模型 Dive into LLMs》**
（[Lordog/dive-into-llms](https://github.com/Lordog/dive-into-llms)，
张倬胜老师团队，课程编号 NIS8021 / NIS3353）课程大纲的一份
**独立、原创的配套实现**。

需要说明清楚的三件事：

1. **本仓库与上游没有代码或文字上的继承关系。** 上游仓库未附带 LICENSE 文件，
   因此本仓库**没有**复制、改编或再分发其任何课件、notebook、文字或图片。
   本仓库只遵循它的**章节大纲顺序**，所有代码、文档、实验设计与结论均为原创；
2. **上游是原始教材，本仓库是配套实现。** 上游的课件与 notebook 讲的是
   在真实模型（HuggingFace + PyTorch + GPU）上怎么做；本仓库讲的是
   同一批机制**从零实现出来**是什么样，以及每个结论在可控实验里能被量化到什么程度。
   两者互补，建议对照阅读——每章文档顶部都直接链到上游对应的课件/教程/脚本；
3. **强烈建议先去看上游。** 如果本仓库对你有帮助，请去给
   [上游仓库](https://github.com/Lordog/dive-into-llms) 点个 star。

## 特点

| | |
| --- | --- |
| **纯 NumPy** | 反向传播、Transformer、KV Cache、LoRA、PPO 全部手写。`dive/autograd.py` 400 余行包含了自动微分的全部机制，可以逐行读完 |
| **不需要 GPU** | 全部 11 章实验在 4 核 CPU 上串行跑完约 14 分钟（快速集合约 4 分钟）。没有一步需要显存 |
| **不需要联网** | 无 PyTorch、无 transformers、不下载权重。数据全部程序生成 |
| **每个结论都有实验** | 文档里的每个数字都来自 `labs/` 下某个脚本的真实输出，不是估算，不是引用 |
| **诚实报告负面结果** | 玩具规模复现不出来的现象（如第 8 章的模态鸿沟）会明确写出来；不成立的技巧（如第 2 章自洽投票没超过贪心）照实报告 |
| **测试即文档** | 291 个 pytest 用例，含全部算子的有限差分梯度检查、KV Cache 一致性、LoRA 合并精确性 |

## 快速开始

```bash
git clone <本仓库地址> && cd <仓库目录>
python3 -m pip install numpy pytest        # 运行时只需要 numpy

python3 -m pytest                          # 291 个用例，约 2.4 秒
python3 -m labs.lab09_gui_agent            # 最快的实验，1 秒内出结果
python3 -m labs.lab01_finetune             # 第 1 章：SFT + LoRA，约 15 秒
```

一次跑通全部实验：

```bash
bash run_all_labs.sh              # 快速集合（第 2、4 章走 --quick），约 4 分钟
bash run_all_labs.sh --all        # 完整版，约 14 分钟
bash run_all_labs.sh --log out/   # 顺便把每章输出存到 out/
```

从 [`docs/00-环境准备.md`](docs/00-环境准备.md) 开始阅读。

## 完整目录

| 章 | 本仓库文档 | 实验脚本 | 上游资料 | 实测结论（headline） | 耗时 |
| --- | --- | --- | --- | --- | --- |
| 1 微调与部署 | [文档](docs/01-微调与部署.md) | [`lab01_finetune`](labs/lab01_finetune.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter1/dive-into-llm.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter1/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter1/dive-tuning.ipynb) | LoRA 用 **2.67%** 可训练参数（9,216 / 345,792）达到与全参数微调相同的 **100%** 组合泛化准确率；合并回主干后 logits 偏差 **1.33e-15** | ~15s |
| 2 提示学习与思维链 | [文档](docs/02-提示学习与思维链.md) | [`lab02_prompting_cot`](labs/lab02_prompting_cot.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter2/dive-into-prompting.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter2/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter2/dive-prompting.ipynb) | 同模型同数据，直接作答 **62%** → 思维链 **72%**；自洽投票把采样损失从 62% 补回 **71%**，但**没有**超过贪心的 72% | ~2.5min |
| 3 知识编辑 | [文档](docs/03-知识编辑.md) | [`lab03_knowledge_edit`](labs/lab03_knowledge_edit.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter3/dive_edit_0410.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter3/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter3/dive_edit.ipynb) | 三种方法有效性都是 **1.000**（毫无区分度）；局部性 ROME 带协方差 **1.000** vs 单位协方差 **0.727**；连续编辑 8 条，后者最低跌到 **35%** | <1s |
| 4 数学推理 | [文档](docs/04-数学推理.md) | [`lab04_math_reasoning`](labs/lab04_math_reasoning.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter4/math.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter4/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter4/sft_math.ipynb) | 三位数加法：直接作答 **0%** / 逆序输出 **1.2%** / 思维链 **92.5%**；逐位误差分析显示个位 0 错、错误全在高位，证明学到的是算法而非查表 | ~8min |
| 5 模型水印 | [文档](docs/05-模型水印.md) | [`lab05_watermark`](labs/lab05_watermark.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter5/watermark.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter5/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter5/watermark.ipynb) | z 值 **8.23 vs 1.08**，检出率 **100%** / 误报率 **0%**；替换 30% token 仍可检出；**熵 0.01 时检出率 0%**——低熵内容打不上水印 | ~90s |
| 6 越狱攻击 | [文档](docs/06-越狱攻击.md) | [`lab06_jailbreak`](labs/lab06_jailbreak.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter6/dive-Jailbreak.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter6/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter6/dive-jailbreak.ipynb) | 输入规范化把表层攻击 ASR 从 **100% 压到 0%**，语义改写仍是 **100%**；叠满防御后 ASR 0% 但**误拒率 100%**——一个必须看懂的假胜利 | ~19s |
| 7 大模型隐写 | [文档](docs/07-大模型隐写.md) | [`lab07_stega`](labs/lab07_stega.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter7/stega.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter7/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter7/llm_stega.ipynb) | 80 bit 无损收发，嵌入率 **2.96 bit/token**，上限 = 模型熵 **3.12 bit**；top_k=2 时文本**过于流畅**（偏离 3.6σ）；改 **1 个 token 还原率归 0** | ~19s |
| 8 多模态模型 | [文档](docs/08-多模态模型.md) | [`lab08_multimodal`](labs/lab08_multimodal.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter8/mllms.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter8/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter8/mllms.ipynb) | 零样本准确率 **6.8% → 76.8%**（无任何标签），R@3 **97%**；batch 2→8 准确率 66.8%→76.8%；**模态鸿沟在此规模未出现**（诚实说明） | ~2s |
| 9 GUI 智能体 | [文档](docs/09-GUI智能体.md) | [`lab09_gui_agent`](labs/lab09_gui_agent.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter9/GUIagent.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter9/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter9/GUIagent.ipynb) | 随机智能体成功率 23.3% / 危险操作触发率 **34.3%**；加护栏后 **33.7% / 0.0%**——安全约束让成功率**上升**了 | <1s |
| 10 智能体安全 | [文档](docs/10-智能体安全.md) | [`lab10_agent_safety`](labs/lab10_agent_safety.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter10/dive-into-safety.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter10/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter10/agent.ipynb) | 间接提示注入在无护栏下触发 **5 次**未授权转账，有护栏 **0 次**；同时正常任务的合法调用**一次都没被挡** | <1s |
| 11 RLHF 安全对齐 | [文档](docs/11-RLHF安全对齐.md) | [`lab11_rlhf`](labs/lab11_rlhf.py) | [课件](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter11/RLHF.pdf) · [教程](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter11/README.md) · [脚本](https://github.com/Lordog/dive-into-llms/blob/main/documents/chapter11/RLHF.ipynb) | 奖励模型成对准确率 **100%**；DPO 的对齐税：β=0.5 → 97.9%/多样性 14，β=0.02 → 100%/多样性 **5**；PPO 去掉 KL 惩罚，奖励没涨而漂移从 +1.21 冲到 **+9.11** | ~18s |

环境准备见 [`docs/00-环境准备.md`](docs/00-环境准备.md)（含把实验迁移到
真实模型的路径：torch/transformers 安装、`HF_ENDPOINT=https://hf-mirror.com`
镜像、清华 pip 源、OpenAI 兼容 API 客户端）。

## 目录结构

```
dive/                  核心库（纯 NumPy，运行时只依赖 numpy）
├── autograd.py        反向模式自动微分：Tensor / Parameter / no_grad / cross_entropy
├── nn.py              Module / Linear / Embedding / RMSNorm / SGD / AdamW / clip_grad_norm
├── tokenizer.py       CharTokenizer / WordTokenizer / BPETokenizer（从零训练）
├── transformer.py     TinyLM：LLaMA 式 pre-norm + RMSNorm + RoPE + SwiGLU + 权重绑定 + KV Cache
├── decoding.py        greedy / temperature / top-k / top-p / 重复惩罚 / generate / beam_search
├── training.py        causal_batch / sft_batch（提示掩码）/ train_causal_lm / perplexity
├── lora.py            LoRALinear / apply_lora / merge_lora / lora_state_dict / trainable_report
├── prompting.py       提示模板 / extract_answer / self_consistency / OpenAICompatClient
├── knowledge_edit.py  AssociativeMemory / FactStore / rome_edit / finetune_edit / evaluate_edit
├── watermark.py       KGW 绿名单水印 GreenListWatermark + z 检验
├── stega.py           Huffman 可逆隐写 HuffmanStego
├── safety.py          KeywordGuard / 7 种攻击 / normalize_defense / PerplexityFilter / evaluate
├── rlhf.py            SequenceRewardModel / bradley_terry_loss / dpo_loss / train_dpo / ppo_train
├── agent.py           ReAct 运行时 / ToolRegistry / SafetyPolicy / 风险分级
├── gui_agent.py       Screen / GUIEnvironment / 无障碍树观测 / 二次确认
└── multimodal.py      MiniCLIP / 对称 InfoNCE / zero_shot_classify / retrieval_at_k

labs/                  11 个可运行实验，每章一个（全部支持 --help）
├── _common.py         输出排版：section / kv / bar / timer / seed_everything
├── _tasks.py          SFTTask / build_sentiment_task / ArithmeticTask（direct/reverse/cot）
├── _corpus.py         槽位语料生成：build_slot_corpus / train_slot_lm / mean_entropy
└── lab01..lab11_*.py

docs/                  中文教程：环境准备 + 11 章
tests/                 291 个 pytest 用例
run_all_labs.sh        按由快到慢的顺序跑通全部实验
```

## 测试说明

```bash
python3 -m pytest                          # 全部 291 个用例，约 2.4 秒
python3 -m pytest tests/test_autograd.py -v # 单个文件
python3 -m pytest -k lora                   # 按关键字筛选
python3 -m compileall -q dive labs tests    # 只做语法检查
```

测试不是走过场，它们固定的是**数值层面的正确性**：

| 测试文件 | 关键断言 |
| --- | --- |
| `test_autograd.py` | 每个算子（mul/sum/silu/softmax/log_softmax/rsqrt/matmul/cat/getitem/cross_entropy）与有限差分对比；`TinyLM` 端到端参数梯度检查 |
| `test_transformer.py` | 注意力严格因果；**KV Cache 与全量前向逐位一致**（误差 ~3e-16）；`max_seq_len` 越界抛错；权重绑定生效 |
| `test_lora.py` | `merge_lora` **数值精确**；`apply_lora` 冻结基座权重；`lora_state_dict` 只含适配器 |
| `test_training.py` | `sft_batch` **恰好**把提示位置标成 `IGNORE_INDEX`，答案位置一个不漏 |
| `test_stega.py` | 多组消息 × 多个 top_k 的往返**逐字节一致**；Huffman 编码前缀无关且确定 |
| `test_knowledge_edit.py` | `rome_edit` 有效性 ≈1.0 且 **rank(ΔW) == 1**；带协方差版本局部性更优 |
| `test_agent.py` | 计算器拒绝 `__import__('os')` 一类输入；`SafetyPolicy` 三层检查各自生效 |
| `test_gui_agent.py` | `reset()` 恢复元素状态（下面那个真实 bug 的回归测试） |
| 其余 | 解码策略、分词器、水印、安全评测、RLHF、多模态、labs 工具的行为契约 |

### 测试抓出来的两个真实 bug

这两个 bug 都是先写代码、后写测试时被抓出来的，修复与回归测试一并提交：

1. **`GUIEnvironment.reset()` 状态泄漏**（`dive/gui_agent.py`）。
   `Screen`/`Element` 是可变对象且跨 episode 共享，上一局把 `dark_mode` 拨到 `on`，
   下一局开局就已经是 `on`——随机智能体的成功率被系统性高估。
   修复：`__init__` 里记下初始外观，`reset()` 逐个恢复。
   这个 bug 只在连续跑多个 episode 时显形，单次调试看不出来。

2. **PPO 的 KL 惩罚放错了位置**（`dive/rlhf.py`）。
   第一版把 KL 当成一项加进损失，训练直接崩。正确做法（InstructGPT 的做法）
   是从**奖励**里扣：$r' = r - \beta\,\mathrm{KL}$。
   加进损失会对每条被采样到的序列都施加方向一致的「降低其概率」梯度，
   而概率之和恒为 1，结果是把概率质量推给没被采样到的序列。

另有一个 `GUIEnvironment.step` 中 `type` 动作的参数解析错误（把整个
`id=value` 当作元素 id 去查找），同样由测试抓出。

## 免责声明

**第 6 章（越狱攻击）、第 7 章（大模型隐写）、第 10 章（智能体安全）
仅用于防御性研究与教学。**

- `dive/safety.py` **不含任何真实有害内容**。「敏感词」是抽象占位
  （危险物品 / 入侵系统 / 伪造证件 / 非法药物），被攻破时的「输出」是固定字符串
  `<模拟：安全过滤被绕过，此处本应是不应输出的内容>`。所有攻击都以**改写模板**
  的形式实现，用于量化防御的覆盖面，不构成任何可用的攻击方法；
- 第 7 章隐写实验隐藏的「秘密消息」是无害占位串（如 `密钥7788`）。
  理解隐写的容量与脆弱性同样是理解**如何检测**隐写的前提；
- 第 10 章的「转账」工具是纯模拟（往一个 Python list 里 append 字符串），
  不接任何真实支付系统；注入载荷是无害的演示文本；
- 本仓库的模型只有几万到几十万参数，在槽位语料上训练，**不具备任何实际能力**。
  这里演示的攻击手法对真实系统的可迁移性没有被验证，也不是本仓库的目的。

请不要将本仓库的任何内容用于攻击真实系统。安全章节的价值在于说明
**防御应当放在哪个位置**（如第 10 章：护栏必须在工具执行前）以及
**如何正确评测防御**（如第 6 章：只报 ASR 不报误拒率是无意义的）。

## 致谢

- 感谢 **上海交通大学 张倬胜（Zhuosheng Zhang）老师团队** 开源
  [《动手学大模型 Dive into LLMs》](https://github.com/Lordog/dive-into-llms)
  这份优秀的中文大模型实践教程（课程 NIS8021 / NIS3353）。本仓库的章节大纲
  完全来自该课程，它定义了「一个大模型课程应该覆盖哪些内容」这个非平凡的问题的答案。
  **请去给上游仓库点 star。**
- 感谢 `docs/` 各章「延伸阅读」中所引论文的作者。本仓库的实现是对这些工作
  核心机制的教学性重述，所有方法的原创性归于原作者。
- 感谢 NumPy 社区——本仓库能存在的全部技术前提就是一个足够好的数组库。

## 许可证

本仓库自身的原创内容以 [MIT License](LICENSE) 发布。

**该许可证仅覆盖本仓库自己的内容**（`dive/`、`labs/`、`docs/`、`tests/`、
`README.md`、`run_all_labs.sh`）。上游 [dive-into-llms](https://github.com/Lordog/dive-into-llms)
仓库未附带许可证文件，其课件、notebook 等材料的一切权利归其作者所有；
本仓库没有复制、再分发或改编其中任何内容，仅以链接与致谢的形式引用。
`docs/` 中引用的论文仅以标题与 arXiv/DOI 链接的形式出现，著作权归各自作者与出版方。
