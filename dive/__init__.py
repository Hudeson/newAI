"""《动手学大模型》配套代码库：纯 NumPy 实现的大模型最小可运行栈。

从自动微分开始，逐层搭出一个能训练、能生成、能对齐、能被攻击也能被防御的
迷你大模型。所有模块只依赖 NumPy，无需 GPU，在普通笔记本上秒级到分钟级即可跑完。

模块速览：

===================  ============================================
模块                  内容
===================  ============================================
``autograd``         反向模式自动微分引擎
``nn``               Linear / Embedding / RMSNorm / AdamW
``tokenizer``        字符级与 BPE 分词器
``transformer``      LLaMA 风格的迷你 Decoder-only 模型（含 KV Cache）
``decoding``         贪心 / 温度 / Top-k / Top-p / 集束搜索
``training``         预训练与指令微调（SFT）循环
``lora``             低秩适配与权重合并
``prompting``        提示模板、答案抽取、自洽投票
``knowledge_edit``   ROME 风格秩一知识编辑
``watermark``        KGW 绿名单水印与 z 检验
``stega``            基于 Huffman 编码的可逆隐写
``safety``           越狱攻击与防御的量化评测
``rlhf``             奖励模型、DPO、PPO
``agent``            ReAct 运行时、工具注册与安全护栏
``gui_agent``        模拟 GUI 环境
``multimodal``       迷你 CLIP 与零样本分类
===================  ============================================
"""

from __future__ import annotations

__version__ = "0.1.0"

from .autograd import Parameter, Tensor, cat, cross_entropy, no_grad
from .decoding import SamplingConfig, beam_search, generate
from .lora import LoRALinear, apply_lora, merge_lora, trainable_report
from .nn import SGD, AdamW, Embedding, Linear, Module, ModuleList, RMSNorm, clip_grad_norm
from .tokenizer import BPETokenizer, CharTokenizer
from .training import TrainConfig, causal_batch, perplexity, sft_batch, train_causal_lm
from .transformer import TinyLM, TinyLMConfig
from .watermark import GreenListWatermark, WatermarkConfig

__all__ = [
    "__version__",
    # autograd / nn
    "Tensor",
    "Parameter",
    "no_grad",
    "cat",
    "cross_entropy",
    "Module",
    "ModuleList",
    "Linear",
    "Embedding",
    "RMSNorm",
    "SGD",
    "AdamW",
    "clip_grad_norm",
    # 分词与模型
    "CharTokenizer",
    "BPETokenizer",
    "TinyLM",
    "TinyLMConfig",
    # 解码与训练
    "SamplingConfig",
    "generate",
    "beam_search",
    "TrainConfig",
    "causal_batch",
    "sft_batch",
    "train_causal_lm",
    "perplexity",
    # 微调与水印
    "LoRALinear",
    "apply_lora",
    "merge_lora",
    "trainable_report",
    "GreenListWatermark",
    "WatermarkConfig",
]
