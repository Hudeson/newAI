"""第 8 章实验：多模态对齐与零样本分类。

多模态大模型的第一步永远是**把两个模态放进同一个向量空间**。CLIP 用对比
学习做这件事：一个 batch 里配对的图文互相靠近，不配对的互相远离。

* 实验 A：训练一个迷你 CLIP，看零样本分类准确率从随机猜提升到多少；
* 实验 B：batch size 的作用——对比学习的负样本来自同一个 batch，
  batch 越大信号越强，这是 CLIP 必须用超大 batch 训练的原因；
* 实验 C：模态鸿沟（modality gap）——即便对齐得很好，图像向量与文本向量
  仍然各自聚成一团，这是多模态表示里一个真实且反直觉的现象；
* 实验 D：噪声水平与准确率，说明"对齐"的上限由数据本身的可分性决定。

用法::

    python -m labs.lab08_multimodal
"""

from __future__ import annotations

import argparse

import numpy as np

from dive.autograd import no_grad
from dive.multimodal import MiniCLIP, SyntheticImageText, retrieval_at_k, train_clip, zero_shot_classify

from ._common import bar, kv, section, timer

CLASSES = ["猫", "狗", "汽车", "飞机", "花朵", "轮船", "苹果", "书本", "山峰", "河流", "桥梁", "钟表"]


def main() -> None:
    parser = argparse.ArgumentParser(description="第 8 章：多模态模型")
    parser.add_argument("--steps", type=int, default=400)
    parser.add_argument("--image-dim", type=int, default=24)
    parser.add_argument("--noise", type=float, default=0.35)
    args = parser.parse_args()

    section("数据：合成图文对")
    dataset = SyntheticImageText(CLASSES, image_dim=args.image_dim, noise=args.noise, seed=0)
    kv("类别数", len(CLASSES))
    kv("图像特征维度", args.image_dim)
    kv("噪声水平", args.noise)
    kv("文本词表", f"{dataset.vocab_size}（字符级，0 为 padding）")
    kv("随机猜准确率", f"{1 / len(CLASSES):.1%}")
    print("\n  每个类别有一个原型向量，图像 = 原型 + 噪声，文本 = 类别名的字符序列。")
    print("  模型必须自己发现「哪张图对应哪个词」，没有任何标签监督。")

    # ------------------------------------------------------------------
    section("实验 A：对比学习训练")
    model = MiniCLIP(args.image_dim, dataset.vocab_size, embed_dim=32, seed=0)
    kv("训练前零样本准确率", f"{zero_shot_classify(model, dataset, n=400):.1%}")
    with timer("对比学习"):
        train_clip(model, dataset, steps=args.steps, batch_size=len(CLASSES), log_every=args.steps // 4)

    accuracy = zero_shot_classify(model, dataset, n=400)
    kv("训练后零样本准确率", f"{accuracy:.1%}")
    kv("图搜文 R@1", f"{retrieval_at_k(model, dataset, n=200, k=1):.1%}")
    kv("图搜文 R@3", f"{retrieval_at_k(model, dataset, n=200, k=3):.1%}")
    with no_grad():
        temperature = float(np.exp(model.log_temperature.data))
    kv("学到的温度系数", f"{temperature:.2f}（CLIP 里这是可学习参数）")

    # ------------------------------------------------------------------
    section("实验 B：batch size 决定负样本数量")
    print(f"  {'batch size':>12}{'负样本数':>10}{'零样本准确率':>14}")
    print("  " + "-" * 52)
    for batch_size in (2, 4, 8, len(CLASSES)):
        trial_data = SyntheticImageText(CLASSES, image_dim=args.image_dim, noise=args.noise, seed=0)
        trial_model = MiniCLIP(args.image_dim, trial_data.vocab_size, embed_dim=32, seed=0)
        train_clip(trial_model, trial_data, steps=args.steps, batch_size=batch_size, verbose=False)
        trial_accuracy = zero_shot_classify(trial_model, trial_data, n=400)
        print(f"  {batch_size:>12}{batch_size - 1:>10}{trial_accuracy:>13.1%}  {bar(trial_accuracy)}")
    print("\n  每个样本的负样本就是同 batch 里的其他样本。batch 越小，对比任务越简单，")
    print("  学到的表示也越粗糙——这就是 CLIP 要用 32768 这种夸张 batch size 的原因。")

    # ------------------------------------------------------------------
    section("实验 C：解剖对齐后的相似度结构")
    images, _, labels = dataset.sample(400)
    with no_grad():
        image_features = model.encode_image(images).data
        text_features = model.encode_text(dataset.class_token_matrix()).data

    same_class_ii, cross_class_ii = [], []
    for class_index in range(len(CLASSES)):
        rows = np.where(labels == class_index)[0]
        if len(rows) > 1:
            block = image_features[rows] @ image_features[rows].T
            same_class_ii.extend(block[np.triu_indices(len(rows), 1)].tolist())
        others = np.where(labels != class_index)[0][:60]
        cross_class_ii.extend((image_features[rows[:10]] @ image_features[others].T).ravel().tolist())

    same_class_it = [float(image_features[i] @ text_features[labels[i]]) for i in range(len(labels))]
    cross_class_it = [
        float(image_features[i] @ text_features[(labels[i] + 1) % len(CLASSES)])
        for i in range(len(labels))
    ]
    gap = float(np.linalg.norm(image_features.mean(axis=0) - text_features.mean(axis=0)))

    print(f"  {'相似度类型':<22}{'余弦相似度':>12}")
    print("  " + "-" * 44)
    print(f"  {'同类 图像-文本（配对）':<22}{np.mean(same_class_it):>+11.3f}")
    print(f"  {'同类 图像-图像':<22}{np.mean(same_class_ii):>+11.3f}")
    print(f"  {'异类 图像-文本':<22}{np.mean(cross_class_it):>+11.3f}")
    print(f"  {'异类 图像-图像':<22}{np.mean(cross_class_ii):>+11.3f}")
    print(f"\n  两个模态中心的距离：{gap:.3f}")

    print("\n  读法：配对相似度（+{:.2f}）远高于任何非配对组合，对齐是成功的。".format(np.mean(same_class_it)))
    print("  值得注意的是，同类的「图像-文本」相似度反而**高于**同类的「图像-图像」——")
    print("  文本向量成了该类别的一个原型中心，各张图像围绕它散开。")
    print("\n  一个诚实的说明：真实 CLIP 里存在明显的「模态鸿沟」（两个模态各自缩在超球面")
    print("  的两个窄锥里，中心相距很远），但在这个规模下它并没有出现。原因是这里的")
    print("  嵌入维度低、两个塔的初始化对称、数据也干净。模态鸿沟主要是高维空间中")
    print("  初始化与对比损失共同作用的产物，不是对比学习的必然结果——这也提醒我们，")
    print("  玩具实验能验证机制，但不能替代在真实规模上的观察。")

    # ------------------------------------------------------------------
    section("实验 D：数据可分性决定上限")
    print(f"  {'噪声水平':>10}{'零样本准确率':>14}")
    print("  " + "-" * 44)
    for noise in (0.1, 0.25, 0.5, 0.8):
        trial_data = SyntheticImageText(CLASSES, image_dim=args.image_dim, noise=noise, seed=0)
        trial_model = MiniCLIP(args.image_dim, trial_data.vocab_size, embed_dim=32, seed=0)
        train_clip(trial_model, trial_data, steps=args.steps, batch_size=len(CLASSES), verbose=False)
        trial_accuracy = zero_shot_classify(trial_model, trial_data, n=400)
        print(f"  {noise:>10.2f}{trial_accuracy:>13.1%}  {bar(trial_accuracy)}")
    print("\n  噪声越大，图像原型本身就越难区分，再好的对齐算法也救不回来。")
    print("  多模态模型的能力边界，首先是数据质量的边界。")


if __name__ == "__main__":
    main()
