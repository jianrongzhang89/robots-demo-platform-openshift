const requestBox = document.querySelector('#request');
const result = document.querySelector('#result');

function render(preview) {
  const route = preview.action === 'list_destinations'
    ? `Available destinations: ${preview.places.join(', ')}`
    : preview.places?.length ? preview.places.join(' → ') : 'No executable route';
  const errors = preview.errors?.length ? `<ul>${preview.errors.map((item) => `<li>${item}</li>`).join('')}</ul>` : '';
  result.innerHTML = `
    <span class="badge ${preview.dispatchable ? 'safe' : 'hold'}">${preview.dispatchable ? 'Preview valid' : 'Dispatch held'}</span>
    <h2>${preview.action}</h2>
    <p class="route">${route}</p>
    ${preview.clarification ? `<p>${preview.clarification}</p>` : ''}
    ${preview.reason ? `<p>${preview.reason}</p>` : ''}
    ${errors}
    <small>Catalog ${preview.catalog_version ?? 'unknown'} · Provider ${preview.provider}</small>`;
}

document.querySelector('#interpret').addEventListener('click', async () => {
  result.textContent = 'Interpreting…';
  try {
    const response = await fetch('/api/interpret', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({text: requestBox.value}),
    });
    render(await response.json());
  } catch (error) {
    result.textContent = `Preview unavailable: ${error}`;
  }
});
