# newAI · Hugging Face 集成

面向 `newAI` 的轻量 Hugging Face Hub / Inference 封装：聊天、文本生成、向量嵌入、模型检索与 CLI。

## 安装

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env   # 填入 HF_TOKEN（可选，部分公开推理不强制）
```

在 [Hugging Face Tokens](https://huggingface.co/settings/tokens) 创建 **Read** 权限 token。  
**聊天 / 生成 / 嵌入**需要 `HF_TOKEN`（Hub 的 `model-info` / `search` 对公开模型可不登录）。  
中国大陆网络可设置 Hub 镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

## 快速开始（Python）

```python
from hf_integration import HuggingFaceClient, ChatSession

client = HuggingFaceClient()

# 单轮对话
reply = client.chat("用一句话介绍 Transformer", system="你是简洁的中文助手")
print(reply.content)

# 多轮会话
session = ChatSession(client, system="你是简洁的中文助手")
print(session.ask("1+1等于几？").content)
print(session.ask("再乘以 3？").content)

# 嵌入
vectors = client.embed(["hello", "你好"])
print(vectors.dimensions, len(vectors.vectors))

# Hub 元数据
print(client.model_info("gpt2").to_dict())
print([m.id for m in client.search_models("bert", limit=5)])
```

## CLI

```bash
# 单轮聊天
python3 -m hf_integration chat "你好，请自我介绍"

# 流式输出
python3 -m hf_integration chat --stream "写一句俳句"

# 交互模式（不传 prompt）
python3 -m hf_integration chat

# 文本生成 / 嵌入 / 模型信息 / 搜索 / 身份
python3 -m hf_integration generate "Once upon a time"
python3 -m hf_integration embed "机器学习" "深度学习"
python3 -m hf_integration model-info gpt2
python3 -m hf_integration search llama --limit 5 --pipeline-tag text-generation
python3 -m hf_integration whoami
```

常用环境变量见 `.env.example`：`HF_TOKEN`、`HF_MODEL`、`HF_EMBED_MODEL`、`HF_PROVIDER`、`HF_ENDPOINT`、`HF_TIMEOUT`。

默认聊天模型：`meta-llama/Llama-3.1-8B-Instruct`（可通过 `HF_MODEL` 或 `--model` 覆盖）。  
推理走 `huggingface_hub.InferenceClient`，`HF_PROVIDER=auto` 会按账号可用的 Inference Providers 自动路由。

## 本地推理（无需 HF_TOKEN）

没有 token 时可用 `transformers` 在 CPU 上跑小模型：

```bash
python3 -m pip install torch transformers --index-url https://download.pytorch.org/whl/cpu
python3 -m pip install transformers  # if not pulled above

python3 -m hf_integration --provider local --model sshleifer/tiny-gpt2 \
  generate "Hello, my name is" --max-new-tokens 20

python3 -m hf_integration --provider local --model sshleifer/tiny-gpt2 \
  chat "用一句话打招呼"
```

## 测试


单元测试全部使用 mock，不需要 token、不下载权重：

```bash
python3 -m pytest
```

## 目录

```
hf_integration/
  config.py    # 环境变量与默认模型
  client.py    # Inference + Hub API 封装
  chat.py      # 多轮 ChatSession
  cli.py       # 命令行入口
tests/         # pytest
```
