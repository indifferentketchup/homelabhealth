import { apiFetch } from './index'

export async function listSkills() {
  return apiFetch('/api/skills', { method: 'GET' })
}

export async function createSkill(data) {
  return apiFetch('/api/skills', { method: 'POST', json: data })
}

export async function deleteSkill(skillId) {
  return apiFetch(`/api/skills/${skillId}`, { method: 'DELETE' })
}

export async function fetchSkillFromUrl(url) {
  return apiFetch('/api/skills/fetch-url', { method: 'POST', json: { url } })
}

export async function searchSkills(query) {
  return apiFetch('/api/skills/search', { method: 'POST', json: { query } })
}

export async function getDawSkills(dawId) {
  return apiFetch(`/api/skills/daws/${dawId}`, { method: 'GET' })
}

export async function addSkillToDaw(dawId, skillId, active = true) {
  return apiFetch(`/api/skills/daws/${dawId}`, {
    method: 'POST',
    json: { skill_id: skillId, active },
  })
}

export async function removeSkillFromDaw(dawId, skillId) {
  return apiFetch(`/api/skills/daws/${dawId}/${skillId}`, { method: 'DELETE' })
}

export async function toggleDawSkill(dawId, skillId, active) {
  return apiFetch(`/api/skills/daws/${dawId}/${skillId}?active=${active}`, {
    method: 'PATCH',
  })
}
