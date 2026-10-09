const requestBox = document.querySelector('#request');
const result = document.querySelector('#result');
let currentTurn = null;
let currentMission = null;

const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

function render(preview) {
  const places = preview.places ?? [];
  const route = preview.action === 'list_destinations'
    ? `Available destinations: ${places.map(escapeHtml).join(', ')}`
    : places.length ? places.map(escapeHtml).join(' → ') : 'No executable route';
  const errors = preview.errors?.length ? `<ul>${preview.errors.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : '';
  const dispatch = preview.dispatchable && preview.preview_id
    ? '<button id="dispatch" class="dispatch">Dispatch mission</button>' : '';
  result.innerHTML = `
    <span class="badge ${preview.dispatchable ? 'safe' : 'hold'}">${preview.dispatchable ? 'Preview valid' : 'Dispatch held'}</span>
    <h2>${escapeHtml(preview.action)}</h2>
    <p class="route">${route}</p>
    ${preview.clarification ? `<p>${escapeHtml(preview.clarification)}</p>` : ''}
    ${preview.reason ? `<p>${escapeHtml(preview.reason)}</p>` : ''}
    ${errors}
    ${dispatch}
    <small>Catalog ${escapeHtml(preview.catalog_version ?? 'unknown')} · Provider ${escapeHtml(preview.provider)}</small>`;
  document.querySelector('#dispatch')?.addEventListener('click', dispatchMission);
}

async function dispatchMission(event) {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = 'Dispatching…';
  try {
    const response = await fetch('/api/v1/missions', {
      method: 'POST',
      headers: {'content-type': 'application/json', 'Idempotency-Key': currentTurn.idempotencyKey},
      body: JSON.stringify({preview_id: currentTurn.preview_id}),
    });
    const mission = await response.json();
    if (!response.ok) throw new Error(mission.detail ?? `HTTP ${response.status}`);
    currentMission = mission;
    renderMission(mission);
    pollMission(mission.mission_id);
  } catch (error) {
    button.disabled = false;
    button.textContent = 'Dispatch mission';
    result.insertAdjacentHTML('beforeend', `<p class="error">Dispatch unavailable: ${escapeHtml(error.message)}</p>`);
  }
}

function renderMission(mission) {
  result.insertAdjacentHTML('beforeend', `
    <div class="mission-card">
      <strong>Mission ${escapeHtml(mission.mission_id)}</strong>
      <span class="mission-status">${escapeHtml(mission.execution)} · RMF ${escapeHtml(mission.rmf_task_id ?? 'pending')}</span>
      <small>Submission ${escapeHtml(mission.submission)} · Revision ${escapeHtml(mission.revision)}</small>
      <div class="evidence-card"><small>Evidence will appear as task state arrives.</small></div>
    </div>`);
}

async function pollMission(missionId) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 5000));
    try {
      await fetch(`/api/v1/missions/${missionId}/sync`, {method: 'POST'});
      const response = await fetch(`/api/v1/missions/${missionId}`);
      const mission = await response.json();
      currentMission = mission;
      const status = document.querySelector('.mission-status');
      if (status) status.textContent = `${mission.execution} · RMF ${mission.rmf_task_id ?? 'pending'}`;
      const evidenceResponse = await fetch(`/api/v1/missions/${missionId}/evidence`);
      const evidence = await evidenceResponse.json();
      const evidenceCard = document.querySelector('.evidence-card');
      if (evidenceCard) evidenceCard.innerHTML = `<strong>${escapeHtml(evidence.classification)}</strong><p>${escapeHtml(evidence.summary)}</p><small>Evidence IDs: ${evidence.evidence_ids.map(escapeHtml).join(', ') || 'none'}</small>`;
      if (['completed', 'failed', 'canceled'].includes(mission.execution)) return;
    } catch (_) {
      const status = document.querySelector('.mission-status');
      if (status) status.textContent = 'status temporarily unavailable';
    }
  }
}

document.querySelector('#interpret').addEventListener('click', async () => {
  result.textContent = 'Interpreting…';
  try {
    const response = await fetch('/api/v1/turns', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({text: requestBox.value}),
    });
    const preview = await response.json();
    if (!response.ok) throw new Error(preview.detail ?? `HTTP ${response.status}`);
    currentTurn = {...preview, idempotencyKey: crypto.randomUUID()};
    render(currentTurn);
  } catch (error) {
    result.textContent = `Preview unavailable: ${escapeHtml(error.message)}`;
  }
});
