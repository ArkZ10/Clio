export type PaperNote = {
  id: string;
  title: string;
  authors: string[];
  year: number;
  arxivId: string;
  tags: string[];
  cluster: number;
  abstract: string;
  notes: string;
  linked: string[];
};

export const paperNotes: PaperNote[] = [
  {
    id: "attention",
    title: "Attention Is All You Need",
    authors: ["Vaswani", "Shazeer", "Parmar", "Uszkoreit"],
    year: 2017,
    arxivId: "1706.03762",
    tags: ["transformers", "nlp", "architecture"],
    cluster: 0,
    abstract:
      "We propose the Transformer, a model architecture relying entirely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
    notes: `## Why it matters

The paper removes recurrence completely and shows that **self-attention** alone is enough to model long-range dependencies, while being far more parallelisable.

## Key mechanics

- Scaled dot-product attention: \`softmax(QKᵀ / √d_k)V\`
- Multi-head attention gives the model several representation subspaces
- Sinusoidal positional encodings inject order without recurrence

## My annotations

The \`√d_k\` scaling is easy to skim past but it is the difference between usable and saturated softmax gradients at larger dimensions. Worth re-deriving.

Open question I keep returning to: how much of the performance is attention versus simply the depth + residual + layernorm recipe? Later ablation work suggests the recipe matters more than people assumed in 2017.`,
    linked: ["bert", "gpt3", "flashattention"],
  },
  {
    id: "bert",
    title: "BERT: Pre-training of Deep Bidirectional Transformers",
    authors: ["Devlin", "Chang", "Lee", "Toutanova"],
    year: 2018,
    arxivId: "1810.04805",
    tags: ["pretraining", "nlp"],
    cluster: 0,
    abstract:
      "BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context in all layers.",
    notes: `## Summary

Masked language modelling turns a unidirectional decoder recipe into a bidirectional encoder, and fine-tuning a single pre-trained stack beats task-specific architectures across GLUE.

## My annotations

The 15% masking rate is arbitrary-ish and later work (RoBERTa) shows the next-sentence-prediction objective contributes very little. The durable idea is *pre-train once, fine-tune cheaply*.`,
    linked: ["attention", "scaling"],
  },
  {
    id: "gpt3",
    title: "Language Models are Few-Shot Learners",
    authors: ["Brown", "Mann", "Ryder"],
    year: 2020,
    arxivId: "2005.14165",
    tags: ["scaling", "in-context", "llm"],
    cluster: 1,
    abstract:
      "We train GPT-3, an autoregressive language model with 175 billion parameters, and test its performance in the few-shot setting without any gradient updates.",
    notes: `## Summary

Scale alone produces in-context learning: the model infers the task from the prompt without weight updates.

## My annotations

The most under-discussed table is the contamination analysis. Also: "few-shot" here means prompt conditioning, which quietly redefined the whole evaluation vocabulary of the field.`,
    linked: ["scaling", "attention", "rag"],
  },
  {
    id: "scaling",
    title: "Scaling Laws for Neural Language Models",
    authors: ["Kaplan", "McCandlish", "Henighan"],
    year: 2020,
    arxivId: "2001.08361",
    tags: ["scaling", "theory"],
    cluster: 1,
    abstract:
      "We study empirical scaling laws for language model performance on the cross-entropy loss, which scales as a power-law with model size, dataset size, and compute.",
    notes: `## Summary

Loss follows smooth power laws in parameters, data and compute — and the exponents let you plan a training run before spending the money.

## My annotations

Superseded in practice by Chinchilla's compute-optimal ratios, but the methodology (fit power laws, extrapolate, verify) is the reusable contribution.`,
    linked: ["gpt3", "bert"],
  },
  {
    id: "rag",
    title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP",
    authors: ["Lewis", "Perez", "Piktus"],
    year: 2020,
    arxivId: "2005.11401",
    tags: ["retrieval", "rag", "grounding"],
    cluster: 2,
    abstract:
      "We explore a general-purpose fine-tuning recipe for retrieval-augmented generation, combining pre-trained parametric and non-parametric memory.",
    notes: `## Summary

Pair a dense retriever with a seq2seq generator so factual knowledge lives in an index you can update, not in frozen weights.

## My annotations

This is the architectural ancestor of every "chat with your documents" product, including the library chat in this app. The failure mode is always retrieval quality, never generation quality.`,
    linked: ["dpr", "gpt3"],
  },
  {
    id: "dpr",
    title: "Dense Passage Retrieval for Open-Domain QA",
    authors: ["Karpukhin", "Oğuz", "Min"],
    year: 2020,
    arxivId: "2004.04906",
    tags: ["retrieval", "embeddings"],
    cluster: 2,
    abstract:
      "We show that retrieval can be practically implemented using dense representations alone, learned from a small number of questions and passages by a dual-encoder framework.",
    notes: `## Summary

A simple dual-encoder trained with in-batch negatives beats BM25 by a wide margin on open-domain QA.

## My annotations

In-batch negatives are the whole trick; hard negative mining is where the remaining points are.`,
    linked: ["rag", "clip"],
  },
  {
    id: "flashattention",
    title: "FlashAttention: Fast and Memory-Efficient Exact Attention",
    authors: ["Dao", "Fu", "Ermon", "Ré"],
    year: 2022,
    arxivId: "2205.14135",
    tags: ["systems", "efficiency"],
    cluster: 3,
    abstract:
      "We propose FlashAttention, an IO-aware exact attention algorithm that uses tiling to reduce memory reads and writes between GPU HBM and on-chip SRAM.",
    notes: `## Summary

Attention was memory-bandwidth bound, not FLOP bound. Tiling + recomputation makes it exact *and* faster.

## My annotations

A reminder that a lot of "algorithmic" progress in ML is really hardware-aware engineering.`,
    linked: ["attention", "lora"],
  },
  {
    id: "lora",
    title: "LoRA: Low-Rank Adaptation of Large Language Models",
    authors: ["Hu", "Shen", "Wallis"],
    year: 2021,
    arxivId: "2106.09685",
    tags: ["fine-tuning", "efficiency"],
    cluster: 3,
    abstract:
      "LoRA freezes the pre-trained model weights and injects trainable rank decomposition matrices into each layer of the Transformer architecture.",
    notes: `## Summary

Fine-tune a low-rank delta instead of full weights: ~10,000× fewer trainable parameters with comparable quality.

## My annotations

Rank 8–16 is usually enough. The adapters composing cleanly is what makes serving many task variants cheap.`,
    linked: ["flashattention", "attention"],
  },
  {
    id: "clip",
    title: "Learning Transferable Visual Models From Natural Language",
    authors: ["Radford", "Kim", "Hallacy"],
    year: 2021,
    arxivId: "2103.00020",
    tags: ["multimodal", "contrastive"],
    cluster: 4,
    abstract:
      "We demonstrate that predicting which caption goes with which image is an efficient and scalable way to learn state-of-the-art image representations from scratch.",
    notes: `## Summary

Contrastive image-text pretraining on 400M pairs yields a shared embedding space with strong zero-shot transfer.

## My annotations

The prompt-engineering appendix ("a photo of a {label}") is the earliest widely-read evidence that prompt phrasing is a real hyperparameter.`,
    linked: ["dpr", "diffusion"],
  },
  {
    id: "diffusion",
    title: "Denoising Diffusion Probabilistic Models",
    authors: ["Ho", "Jain", "Abbeel"],
    year: 2020,
    arxivId: "2006.11239",
    tags: ["generative", "diffusion"],
    cluster: 4,
    abstract:
      "We present high quality image synthesis results using diffusion probabilistic models, a class of latent variable models inspired by nonequilibrium thermodynamics.",
    notes: `## Summary

Learn to reverse a fixed Gaussian noising process; the simplified ε-prediction objective is what made it trainable in practice.

## My annotations

Sampling cost is the practical constraint — everything since has been about taking fewer steps.`,
    linked: ["clip"],
  },
];

export const noteById = (id: string) => paperNotes.find((n) => n.id === id);
