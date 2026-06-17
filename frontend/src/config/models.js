/**
 * Model configuration  -  baked at build time.
 * Maps homelabhealth's 7 hardware tiers to model capabilities.
 * Model IDs align with backend `bundled_providers.TIER_CHAT_MODELS`.
 *
 * Usage:
 *   import { getModelsForTier, getModelById } from '@/config/models'
 *   const models = getModelsForTier('gpu-8gb')  // → [medgemma, external]
 */

/**
 * @typedef {Object} ChatModel
 * @property {string} id - Backend model ID
 * @property {string} name - Human-readable label
 * @property {string} provider - 'bundled' | 'external'
 * @property {string} description - Capability summary
 * @property {string[]} tiers - Tiers this model supports
 * @property {number} contextWindow - Max context window (tokens)
 * @property {boolean} reasoningEffort - Supports reasoning/thinking
 * @property {boolean} vision - Supports multimodal vision
 */

/** @type {ChatModel[]} */
export const CHAT_MODELS = [
  {
    id: 'qwen-chat',
    name: 'Qwen3.5 0.8B',
    provider: 'bundled',
    description: 'Compact MTP model for CPU-min systems  -  no vision',
    tiers: ['cpu-min'],
    contextWindow: 8192,
    reasoningEffort: false,
    vision: false,
  },
  {
    id: 'medgemma',
    name: 'MedGemma 4B',
    provider: 'bundled',
    description: 'Medical-tuned multimodal 4B (Q4 on cpu/gpu-4gb, Q8 on gpu-8gb/gpu-16gb)',
    tiers: ['cpu-std', 'gpu-4gb', 'gpu-8gb', 'gpu-16gb'],
    contextWindow: 32768,
    reasoningEffort: false,
    vision: true,
  },
  {
    id: 'medgemma-27b',
    name: 'MedGemma 27B',
    provider: 'bundled',
    description: 'Large medical-tuned multimodal 27B for high-VRAM systems',
    tiers: ['gpu-24gb+'],
    contextWindow: 65536,
    reasoningEffort: false,
    vision: true,
  },
  {
    id: 'external',
    name: 'External',
    provider: 'external',
    description: 'Bring your own OpenAI-compatible endpoint  -  capabilities vary',
    tiers: ['external'],
    contextWindow: 65536,
    reasoningEffort: true,
    vision: true,
  },
]

/** Per-model context window overrides for specific tiers. */
const TIER_CONTEXT_OVERRIDES = {
  medgemma: {
    'cpu-std': 8192,
    'gpu-4gb': 32768,
    'gpu-8gb': 32768,
    'gpu-16gb': 32768,
  },
}

/**
 * Returns viable ChatModel entries for a given hardware tier.
 * @param {string} tier
 * @returns {ChatModel[]}
 */
export function getModelsForTier(tier) {
  return CHAT_MODELS.filter((m) => m.tiers.includes(tier))
}

/**
 * Returns a single ChatModel by its id.
 * @param {string} id
 * @returns {ChatModel|undefined}
 */
export function getModelById(id) {
  return CHAT_MODELS.find((m) => m.id === id)
}

/**
 * Returns the effective context window for a model+tier combination,
 * respecting tier-specific overrides.
 * @param {string} modelId
 * @param {string} tier
 * @returns {number}
 */
export function getContextWindowForTier(modelId, tier) {
  const model = getModelById(modelId)
  if (!model) return 4096
  const overrides = TIER_CONTEXT_OVERRIDES[modelId]
  if (overrides && overrides[tier] !== undefined) return overrides[tier]
  return model.contextWindow
}

/**
 * Returns whether a model+tier combination supports vision.
 * External model relies on the user's endpoint; returns true optimistically.
 * @param {string} modelId
 * @param {string} tier
 * @returns {boolean}
 */
export function hasVisionForTier(modelId, tier) {
  if (modelId === 'external') return true
  // cpu-min is the only tier without vision.
  if (tier === 'cpu-min') return false
  const model = getModelById(modelId)
  return model ? model.vision : false
}

/** Per-tier default model id. */
export const DEFAULT_MODELS = {
  'cpu-min': 'qwen-chat',
  'cpu-std': 'medgemma',
  'gpu-4gb': 'medgemma',
  'gpu-8gb': 'medgemma',
  'gpu-16gb': 'medgemma',
  'gpu-24gb+': 'medgemma-27b',
  external: 'external',
}

/**
 * Tier metadata with display labels and context window.
 * @type {Array<{id: string, label: string, description: string, contextWindow: number}>}
 */
export const TIERS = [
  { id: 'cpu-min', label: 'CPU Min', description: '<16 GB RAM, no GPU', contextWindow: 8192 },
  { id: 'cpu-std', label: 'CPU Std', description: '≥16 GB RAM, no GPU', contextWindow: 8192 },
  { id: 'gpu-4gb', label: 'GPU 4GB', description: '4–5 GB VRAM', contextWindow: 32768 },
  { id: 'gpu-8gb', label: 'GPU 8GB', description: '6–11 GB VRAM', contextWindow: 32768 },
  { id: 'gpu-16gb', label: 'GPU 16GB', description: '12–23 GB VRAM', contextWindow: 32768 },
  { id: 'gpu-24gb+', label: 'GPU 24GB+', description: '≥24 GB VRAM', contextWindow: 65536 },
  { id: 'external', label: 'External', description: 'Bring your own endpoint', contextWindow: 65536 },
]
