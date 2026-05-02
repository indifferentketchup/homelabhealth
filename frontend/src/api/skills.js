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

export async function getWorkspaceSkills(workspaceId) {
  return apiFetch(`/api/skills/workspaces/${workspaceId}`, { method: 'GET' })
}

export async function addSkillToWorkspace(workspaceId, skillId, active = true) {
  return apiFetch(`/api/skills/workspaces/${workspaceId}`, {
    method: 'POST',
    json: { skill_id: skillId, active },
  })
}

export async function removeSkillFromWorkspace(workspaceId, skillId) {
  return apiFetch(`/api/skills/workspaces/${workspaceId}/${skillId}`, { method: 'DELETE' })
}

export async function toggleWorkspaceSkill(workspaceId, skillId, active) {
  return apiFetch(`/api/skills/workspaces/${workspaceId}/${skillId}?active=${active}`, {
    method: 'PATCH',
  })
}
