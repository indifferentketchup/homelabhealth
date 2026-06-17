/**
 * Tier definitions and related helpers shared by SystemTab sub-components.
 *
 * Source: hlh_phase0_design.md §Tier definitions (sysinfo + UX).
 * Phase 1 update (hlh_phase1_design.md §Tier model defaults): chat strings
 * now reflect MedGemma defaults for cpu-std and up. Footprints are rough.
 */

export const TIERS = [
  {
    id: 'cpu-min',
    label: 'CPU  -  minimal',
    chat: 'Qwen3.5 0.8B Q8_0',
    embed: 'Qwen3-Embedding-0.6B (1024-dim)',
    rerank: 'Qwen3-Reranker-0.6B',
    vision: ' -  (not available)',
    footprint: '~1.5 GB RAM peak · ~0.9 GB disk · 8K context',
    diskGb: 1,
    detect: '<16 GB RAM, no GPU',
    isCpu() { return true },
    rationale(sysinfo) {
      const ram = Number(sysinfo?.ram_total_gb) || 0
      const apple = !!sysinfo?.apple_silicon
      return apple
        ? `Apple Silicon, ${ram} GB unified (below 16 GB threshold) → cpu-min`
        : `${ram} GB RAM, no GPU → cpu-min`
    },
  },
  {
    id: 'cpu-std',
    label: 'CPU  -  standard',
    chat: 'MedGemma 1.5 4B Q4_K_M',
    embed: 'Qwen3-Embedding-0.6B (1024-dim)',
    rerank: 'Qwen3-Reranker-0.6B',
    vision: 'MedGemma 1.5 4B (mmproj)',
    footprint: '~4 GB RAM peak · ~2.8 GB disk · 8K context',
    diskGb: 3,
    detect: '≥16 GB RAM, no GPU',
    isCpu() { return true },
    rationale(sysinfo) {
      const ram = Number(sysinfo?.ram_total_gb) || 0
      return `${ram} GB RAM, no usable GPU → cpu-std`
    },
  },
  {
    id: 'gpu-4gb',
    label: 'GPU  -  4 GB class',
    chat: 'MedGemma 1.5 4B Q4_K_M',
    embed: 'Qwen3-Embedding-0.6B (1024-dim)',
    rerank: 'Qwen3-Reranker-0.6B',
    vision: 'MedGemma 1.5 4B (mmproj)',
    footprint: '~3.5 GB VRAM peak · ~2.8 GB disk · 32K context',
    diskGb: 3,
    detect: '4–5 GB VRAM',
    isCpu() { return false },
    rationale(sysinfo) {
      const gpus = Array.isArray(sysinfo?.gpus) ? sysinfo.gpus : []
      const maxVramMb = Math.max(0, ...gpus.map((g) => Number(g?.memory_total_mb) || 0))
      const maxVramGb = Math.floor(maxVramMb / 1024)
      return `${maxVramGb} GB VRAM detected → gpu-4gb (partial offload)`
    },
  },
  {
    id: 'gpu-8gb',
    label: 'GPU  -  8 GB class',
    chat: 'MedGemma 1.5 4B Q8_0',
    embed: 'Qwen3-Embedding-0.6B (1024-dim)',
    rerank: 'Qwen3-Reranker-0.6B',
    vision: 'MedGemma 1.5 4B (mmproj)',
    footprint: '~6 GB VRAM peak · ~4.5 GB disk · 32K context',
    diskGb: 5,
    detect: '6–11 GB VRAM',
    isCpu() { return false },
    rationale(sysinfo) {
      const gpus = Array.isArray(sysinfo?.gpus) ? sysinfo.gpus : []
      const maxVramMb = Math.max(0, ...gpus.map((g) => Number(g?.memory_total_mb) || 0))
      const maxVramGb = Math.floor(maxVramMb / 1024)
      return `${maxVramGb} GB VRAM detected → gpu-8gb`
    },
  },
  {
    id: 'gpu-16gb',
    label: 'GPU  -  16 GB class',
    chat: 'MedGemma 1.5 4B Q8_0',
    embed: 'Qwen3-Embedding-0.6B (1024-dim)',
    rerank: 'Qwen3-Reranker-0.6B',
    vision: 'MedGemma 1.5 4B (mmproj)',
    footprint: '~9 GB VRAM peak · ~6 GB disk · 32K context',
    diskGb: 6,
    detect: '12–23 GB VRAM',
    isCpu() { return false },
    rationale(sysinfo) {
      const gpus = Array.isArray(sysinfo?.gpus) ? sysinfo.gpus : []
      const maxVramMb = Math.max(0, ...gpus.map((g) => Number(g?.memory_total_mb) || 0))
      const maxVramGb = Math.floor(maxVramMb / 1024)
      return `${maxVramGb} GB VRAM detected → gpu-16gb`
    },
  },
  {
    id: 'gpu-24gb+',
    label: 'GPU  -  24 GB+',
    chat: 'MedGemma 27B Q4_K_M',
    embed: 'Qwen3-Embedding-0.6B (1024-dim)',
    rerank: 'Qwen3-Reranker-0.6B',
    vision: 'MedGemma 27B (mmproj)',
    footprint: '~18 GB VRAM peak · ~18 GB disk · 64K context',
    diskGb: 18,
    detect: '≥24 GB VRAM',
    isCpu() { return false },
    rationale(sysinfo) {
      const gpus = Array.isArray(sysinfo?.gpus) ? sysinfo.gpus : []
      const maxVramMb = Math.max(0, ...gpus.map((g) => Number(g?.memory_total_mb) || 0))
      const maxVramGb = Math.floor(maxVramMb / 1024)
      return `${maxVramGb} GB VRAM detected → gpu-24gb+`
    },
  },
  {
    id: 'apple-mlx',
    label: 'Apple Silicon (MLX)  -  deferred to Phase 6',
    chat: 'MedGemma 4B MLX',
    embed: 'bge-large-en-v1.5 MLX',
    rerank: 'bge-reranker-v2-m3 MLX',
    vision: 'Qwen2.5-VL MLX',
    footprint: '~12–16 GB unified · varies',
    diskGb: 12,
    detect: 'Apple Silicon, ≥16 GB unified',
    isCpu() { return false },
    rationale(sysinfo) {
      const ram = Number(sysinfo?.ram_total_gb) || 0
      return `Apple Silicon, ${ram} GB unified memory → apple-mlx`
    },
  },
  {
    id: 'external',
    label: 'External providers only',
    chat: ' - ',
    embed: ' - ',
    rerank: ' - ',
    vision: ' - ',
    footprint: 'No local model footprint',
    diskGb: 0,
    detect: 'Operator chose external only',
    isCpu() { return false },
    rationale() { return 'External providers only' },
  },
]

export const VISIBLE_TIERS = TIERS.filter((t) => t.id !== 'external')

export function formatGpu(g) {
  if (!g || typeof g !== 'object') return null
  const name = (typeof g.name === 'string' && g.name.trim()) || 'GPU'
  const mb = Number(g.memory_total_mb)
  if (!Number.isFinite(mb) || mb <= 0) return name
  const gb = Math.round((mb / 1024) * 10) / 10
  return `${name} (${gb} GB)`
}

export function rationaleFor(sysinfo, recommended) {
  if (!sysinfo || typeof sysinfo !== 'object') {
    return 'no hardware detected yet  -  click Re-detect'
  }
  const tier = TIERS.find((t) => t.id === recommended)
  return tier ? tier.rationale(sysinfo) : `${recommended} selected`
}
